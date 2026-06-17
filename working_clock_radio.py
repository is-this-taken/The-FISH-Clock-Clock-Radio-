from machine import Pin, I2C, SPI
import time
import _thread
from ssd1309 import Display


# HARDWARE CONFIGURATION & PIN OUTS

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


# GLOBAL MULTI-THREAD STATE

Count = 2
FrequencyStep = 139
UpdateDisplay = True
PrevAB = (EncoderA.value() << 1) | EncoderB.value()

hour = 0
minute = 0
alm_hour = 0
alm_min = 0
seconds = 0

# Raw position trackers for smooth half-step debouncing
encoder_pos_vol  = Count * 2
encoder_pos_freq = FrequencyStep * 2
encoder_pos_hr   = hour * 2
encoder_pos_min  = minute * 2
encoder_pos_ahr  = alm_hour * 2
encoder_pos_amin = alm_min * 2

last_second_tick = time.ticks_ms()
AdjustMode = 0
LP = False
AlarmFiring = False
alarm_flash_state = False
alarm_flash_last = time.ticks_ms()
alarm_flash_end = 0


# CORE 0: ENCODER ISR

def VolumeEncoderInterrupt(pin):
    global Count, PrevAB, UpdateDisplay, last_turn, AdjustMode
    global encoder_pos_vol, encoder_pos_freq, encoder_pos_hr, encoder_pos_min, encoder_pos_ahr, encoder_pos_amin
    global hour, minute, alm_hour, alm_min, FrequencyStep

    table = [[0, -1, +1, 0], [+1, 0, 0, -1], [-1, 0, 0, +1], [0, +1, -1, 0]]
    curr = (EncoderA.value() << 1) | EncoderB.value()
    delta = table[PrevAB][curr]
    PrevAB = curr

    if delta != 0:
        if time.ticks_diff(time.ticks_ms(), last_turn) < 20:
            return
        last_turn = time.ticks_ms()

        # MODE 0: VOLUME
        if AdjustMode == 0:
            new_pos = encoder_pos_vol + delta
            if 0 <= new_pos <= 30:
                encoder_pos_vol = new_pos
                new_vol = encoder_pos_vol // 2
                if new_vol != Count:
                    Count = new_vol
                    fm_radio.SetVolume(Count)
                    fm_radio.ProgramRadio()
                    UpdateDisplay = True

        # MODE 1: FREQUENCY
        elif AdjustMode == 1:
            new_pos = encoder_pos_freq + delta
            if 0 <= new_pos <= 400: 
                encoder_pos_freq = new_pos
                new_step = encoder_pos_freq // 2
                if new_step != FrequencyStep:
                    FrequencyStep = new_step
                    new_freq = round(88.0 + (FrequencyStep * 0.1), 1)
                    fm_radio.SetFrequency(new_freq)
                    fm_radio.ProgramRadio()
                    UpdateDisplay = True

        # MODE 2: HOUR
        elif AdjustMode == 2:
            encoder_pos_hr = (encoder_pos_hr + delta) % 48
            new_val = encoder_pos_hr // 2
            if new_val != hour:
                hour = new_val
                UpdateDisplay = True

        # MODE 3: MINUTE
        elif AdjustMode == 3:
            encoder_pos_min = (encoder_pos_min + delta) % 120
            new_val = encoder_pos_min // 2
            if new_val != minute:
                minute = new_val
                UpdateDisplay = True

        # MODE 4: ALARM HOUR
        elif AdjustMode == 4:
            encoder_pos_ahr = (encoder_pos_ahr + delta) % 48
            new_val = encoder_pos_ahr // 2
            if new_val != alm_hour:
                alm_hour = new_val
                UpdateDisplay = True

        # MODE 5: ALARM MINUTE
        elif AdjustMode == 5:
            encoder_pos_amin = (encoder_pos_amin + delta) % 120
            new_val = encoder_pos_amin // 2
            if new_val != alm_min:
                alm_min = new_val
                UpdateDisplay = True



# RADIO CHIP DRIVER CLASS

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
        self.Settings = self.Settings[:8]

    def ProgramRadio(self):
        self.UpdateSettings()
        self.radio_i2c.writeto(self.i2c_device_address, self.Settings)



# CORE 1 DISPLAY THREAD

def display_core_thread():
    global UpdateDisplay, Count, AdjustMode, LP, seconds, hour, minute, alm_hour, alm_min
    global AlarmFiring, alarm_flash_state

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

            if AlarmFiring and alarm_flash_state:
                oled.draw_text8x8(0, 0, "!!! ALARM !!!")
            else:
                oled.draw_text8x8(0, 0, "Alarm: %02d:%02d" % (alm_hour, alm_min))

            if LP:
                oled.draw_text8x8(99, 0, "ON")
            else:
                oled.draw_text8x8(99, 0, "OFF")

            oled.draw_text8x8(0, 10, "Time: %02d:%02d:%02d" % (hour, minute, seconds))
            oled.draw_text8x8(0, 20, "Freq: %5.1f MHz" % fm_radio.Frequency)
            oled.draw_text8x8(0, 32, "Volume: %2d / 15" % Count)

            mode_names = ["VOL", "FREQ", "HOUR", "MIN", "ALM HR", "ALM MIN"]
            mode_text = mode_names[AdjustMode]
            oled.draw_text8x8(0, 44, "Mode: %s" % mode_text)

            bar_width = int((Count / 15) * 128)
            oled.draw_rectangle(0, 56, bar_width, 5)

            oled.present()

        time.sleep_ms(15)



# STARTUP

fm_radio = Radio(98.5, 2, False)

EncoderA.irq(handler=VolumeEncoderInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=False)
EncoderB.irq(handler=VolumeEncoderInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=False)

_thread.start_new_thread(display_core_thread, ())


# MAIN LOOP

last_button_raw = 1
debounced_button = 1
last_debounce_time = 0
button_down_time = 0
long_press_done = False
LONG_PRESS_MS = 1000

while True:
    now = time.ticks_ms()
    
    
    # HARDWARE BUTTON DEBOUNCE LOGIC
    
    button_raw = ModeButton.value()

    if button_raw != last_button_raw:
        last_debounce_time = now
    last_button_raw = button_raw

    if time.ticks_diff(now, last_debounce_time) > 50:
        if button_raw != debounced_button:
            debounced_button = button_raw
            
            # Button was just PRESSED (Transition to 0)
            if debounced_button == 0:
                button_down_time = now
                long_press_done = False
                
            # Button was just RELEASED (Transition to 1)
            elif debounced_button == 1:
                # SHORT PRESS (Mode switch)
                if not long_press_done:
                    AdjustMode += 1
                    if AdjustMode > 5:
                        AdjustMode = 0
                    UpdateDisplay = True

    
    # LONG PRESS DETECTION
    
    if debounced_button == 0:
        if not long_press_done and time.ticks_diff(now, button_down_time) > LONG_PRESS_MS:
            long_press_done = True
            LP = not LP
            if LP:
                fm_radio.SetMute(True)
            else:
                fm_radio.SetMute(False)
            fm_radio.ProgramRadio()
            UpdateDisplay = True

    
    # SYSTEM TIMER & EXACT-SECOND ALARM TRIGGER
    
    time_advanced = False
    
    # This loop counts every single literal second
    while time.ticks_diff(now, last_second_tick) >= 1000:
        last_second_tick = time.ticks_add(last_second_tick, 1000)
        seconds += 1
        time_advanced = True
        
        if seconds >= 60:
            seconds = 0
            minute += 1
            encoder_pos_min = minute * 2  
            
            if minute >= 60:
                minute = 0
                encoder_pos_min = 0
                hour += 1
                encoder_pos_hr = hour * 2 
                
                if hour >= 24:
                    hour = 0
                    encoder_pos_hr = 0
                    
        # By putting this check INSIDE the second-counter, it evaluates 
        # exactly once per second. It will only fire on the true 00 second mark.
        if LP and hour == alm_hour and minute == alm_min and seconds == 0:
            print("ALARM TRIGGERED!")
            LP = False
            AlarmFiring = True
            alarm_flash_state = True
            alarm_flash_last = now
            alarm_flash_end = time.ticks_add(now, 5000)
            Count = 8
            encoder_pos_vol = Count * 2
            fm_radio.SetMute(False)
            fm_radio.SetVolume(Count)
            fm_radio.ProgramRadio()
            UpdateDisplay = True

    if AlarmFiring:
        if time.ticks_diff(now, alarm_flash_last) >= 300:
            alarm_flash_last = time.ticks_add(alarm_flash_last, 300)
            alarm_flash_state = not alarm_flash_state
            UpdateDisplay = True

        if time.ticks_diff(now, alarm_flash_end) >= 0:
            AlarmFiring = False
            alarm_flash_state = False
            UpdateDisplay = True

    if time_advanced:
        UpdateDisplay = True
        
    time.sleep_ms(20)

