from machine import Pin, I2C, SPI
import time
import _thread
from ssd1309 import Display

# ----------------------------------------------------
# HARDWARE CONFIGURATION & PIN OUTS
# ----------------------------------------------------
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64

# Encoder Pins
EncoderA = Pin(4, Pin.IN)
EncoderB = Pin(2, Pin.IN)

# Mode Button (active low)
ModeButton = Pin(15, Pin.IN, Pin.PULL_UP)

# For rotary encoder debounce
last_turn = 0

# Display SPI Pins
spi_sck = Pin(18)
spi_sda = Pin(19)
spi_res = Pin(21)
spi_dc  = Pin(20)
spi_cs  = Pin(17)
SPI_DEVICE = 0

# ----------------------------------------------------
# GLOBAL MULTI-THREAD STATE
# ----------------------------------------------------
Count = 2
encoder_pos = 4
UpdateDisplay = True
PrevAB = (EncoderA.value() << 1) | EncoderB.value()

hour = 00
minute = 00
alm_hour = 00
alm_min = 00

AdjustMode = 0
LP = False

FrequencyStep = 139

# ------------------- ADDED (LONG PRESS) -------------------
button_down_time = 0
long_press_done = False
LONG_PRESS_MS = 1000
# ----------------------------------------------------------


# ----------------------------------------------------
# CORE 0: ENCODER ISR
# ----------------------------------------------------
def VolumeEncoderInterrupt(pin):
    global Count, PrevAB, UpdateDisplay, last_turn
    global encoder_pos, AdjustMode, FrequencyStep

    table = [
        [0, -1, +1, 0],
        [+1, 0, 0, -1],
        [-1, 0, 0, +1],
        [0, +1, -1, 0]
    ]

    curr = (EncoderA.value() << 1) | EncoderB.value()
    delta = table[PrevAB][curr]
    PrevAB = curr

    if delta != 0:

        if time.ticks_diff(time.ticks_ms(), last_turn) < 20:
            return

        last_turn = time.ticks_ms()

        # ------------------------------------------------
        # VOLUME MODE
        # ------------------------------------------------
        if AdjustMode == 0:

            new_pos = encoder_pos + delta

            if 0 <= new_pos <= 30:
                encoder_pos = new_pos

                new_vol = encoder_pos // 2

                if new_vol != Count:
                    Count = new_vol
                    fm_radio.SetVolume(Count)
                    fm_radio.ProgramRadio()
                    UpdateDisplay = True

        # ------------------------------------------------
        # FREQUENCY MODE
        # ------------------------------------------------
        else:

            new_step = FrequencyStep + delta

            if 0 <= new_step <= 200:
                FrequencyStep = new_step

                new_freq = round(88.0 + (FrequencyStep * 0.1), 1)

                if new_freq != fm_radio.Frequency:
                    fm_radio.SetFrequency(new_freq)
                    fm_radio.ProgramRadio()
                    UpdateDisplay = True


# ----------------------------------------------------
# RADIO CHIP DRIVER CLASS
# ----------------------------------------------------
class Radio:
    def __init__(self, NewFrequency, NewVolume, NewMute):
        self.Volume = 2
        self.Frequency = 88
        self.Mute = False
        self.needs_tune = True

        self.SetVolume(NewVolume)
        self.SetFrequency(NewFrequency)
        self.SetMute(NewMute)

        self.i2c_sda = Pin(26)
        self.i2c_scl = Pin(27)
        self.i2c_device = 1
        self.i2c_device_address = 0x10
        self.Settings = bytearray(8)

        self.radio_i2c = I2C(self.i2c_device, scl=self.i2c_scl, sda=self.i2c_sda, freq=200000)
        self.ProgramRadio()

    def SetVolume(self, NewVolume):
        try:
            NewVolume = int(NewVolume)
        except:
            return False
        if not isinstance(NewVolume, int) or (NewVolume < 0 or NewVolume >= 16):
            return False
        self.Volume = NewVolume
        return True

    def SetFrequency(self, NewFrequency):
        try:
            NewFrequency = float(NewFrequency)
        except:
            return False
        if not isinstance(NewFrequency, float) or (NewFrequency < 88.0 or NewFrequency > 108.0):
            return False
        self.Frequency = NewFrequency
        self.needs_tune = True
        return True

    def SetMute(self, NewMute):
        try:
            self.Mute = bool(int(NewMute))
        except:
            return False
        return True

    def ComputeChannelSetting(self, Frequency):
        Frequency = int(Frequency * 10) - 870
        ByteCode = bytearray(2)
        ByteCode[0] = (Frequency >> 2) & 0xFF
        ByteCode[1] = ((Frequency & 0x03) << 6) & 0xC0
        return ByteCode

    def UpdateSettings(self):
        self.Settings = bytearray(8)
        self.Settings[0] = 0x80 if self.Mute else 0xC0
        self.Settings[1] = 0x09 | 0x04

        channel = self.ComputeChannelSetting(self.Frequency)
        self.Settings[2] = channel[0]
        self.Settings[3] = channel[1]

        if self.needs_tune:
            self.Settings[3] |= 0x10
            self.needs_tune = False

        self.Settings[4] = 0x04
        self.Settings[5] = 0x00
        self.Settings[6] = 0x84
        self.Settings[7] = 0x80 + self.Volume

    def ProgramRadio(self):
        self.UpdateSettings()
        self.radio_i2c.writeto(self.i2c_device_address, self.Settings)


# ----------------------------------------------------
# CORE 1 DISPLAY THREAD
# ----------------------------------------------------
def display_core_thread():
    global UpdateDisplay, Count, AdjustMode, LP

    oled_spi = SPI(SPI_DEVICE, baudrate=1000000, sck=spi_sck, mosi=spi_sda)

    oled = Display(
        spi=oled_spi,
        cs=spi_cs,
        dc=spi_dc,
        rst=spi_res,
        width=SCREEN_WIDTH,
        height=SCREEN_HEIGHT,
        flip=False
    )

    while True:

        if UpdateDisplay:

            UpdateDisplay = False

            oled.clear_buffers()

            oled.draw_text8x8(0, 0, "Alarm: 10:15")

            # ------------------- ADDED (LP DISPLAY) -------------------
            if LP:
                oled.draw_text8x8(99, 0, "ON")
            else:
                oled.draw_text8x8(99, 0, "OFF")
            # ----------------------------------------------------------

            oled.draw_text8x8(0,10, "Time: 10:15 00")

            oled.draw_text8x8(0,20, "Freq: %5.1f MHz" % fm_radio.Frequency)

            oled.draw_text8x8(0,32, "Volume: %2d / 15" % Count)

            mode_names = [
                "VOL",
                "FREQ",
                "HOUR",
                "MIN",
                "ALM HR",
                "ALM MIN"
            ]

            mode_text = mode_names[AdjustMode]

            oled.draw_text8x8(0,44, "Mode: %s" % mode_text)

            bar_width = int((Count / 15) * 128)
            oled.draw_rectangle(0, 56, bar_width, 5)

            oled.present()

        time.sleep_ms(15)


# ----------------------------------------------------
# STARTUP
# ----------------------------------------------------
fm_radio = Radio(101.9, 2, False)

EncoderA.irq(handler=VolumeEncoderInterrupt,
              trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING,
              hard=False)

EncoderB.irq(handler=VolumeEncoderInterrupt,
              trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING,
              hard=False)

_thread.start_new_thread(display_core_thread, ())

# ----------------------------------------------------
# MAIN LOOP (ONLY MODIFIED HERE)
# ----------------------------------------------------
last_button = 1

while True:

    button = ModeButton.value()
    now = time.ticks_ms()

    # button pressed
    if button == 0 and last_button == 1:
        button_down_time = now
        long_press_done = False

    # held down → long press check
    if button == 0:

        if (not long_press_done and
            time.ticks_diff(now, button_down_time) > LONG_PRESS_MS):

            long_press_done = True
            LP = not LP
            UpdateDisplay = True

    # released → short press
    if button == 1 and last_button == 0:

        if not long_press_done:

            AdjustMode += 1

            if AdjustMode > 5:
                AdjustMode = 0

            print("Mode =", AdjustMode)
            UpdateDisplay = True

        time.sleep_ms(200)

    last_button = button
    time.sleep_ms(20)
