

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
Count = 2             # Global Volume tracker (0 to 15)
encoder_pos = 4
UpdateDisplay = True  # Signal flag for Core 1 to refresh display
PrevAB = (EncoderA.value() << 1) | EncoderB.value()

# ----------------------------------------------------
# CORE 0: ENCODER INTERRUPT SERVICE ROUTINE (ISR)
# ----------------------------------------------------
def VolumeEncoderInterrupt(pin):
    # ADD 'encoder_pos' to the global list
    global Count, PrevAB, UpdateDisplay, last_turn, encoder_pos
    
    table = [[0, -1, +1, 0], [+1, 0, 0, -1], [-1, 0, 0, +1], [0, +1, -1, 0]]
    curr = (EncoderA.value() << 1) | EncoderB.value()
    delta = table[PrevAB][curr]
    PrevAB = curr

    if delta != 0:
        if time.ticks_diff(time.ticks_ms(), last_turn) < 20: 
            return
        last_turn = time.ticks_ms()

        # 1. Update the raw internal position (max is 30, because 30 // 2 = 15)
        new_pos = encoder_pos + delta
        if 0 <= new_pos <= 30:
            encoder_pos = new_pos
            
            # 2. Divide by 2 to turn 2 steps into 1 volume click
            new_vol = encoder_pos // 2
            
            # 3. Only update the radio if the actual volume number changed
            if new_vol != Count:
                Count = new_vol
                fm_radio.SetVolume(Count)
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
        self.Settings[2:3] = self.ComputeChannelSetting(self.Frequency)
        if self.needs_tune:
            self.Settings[3] = self.Settings[3] | 0x10
            self.needs_tune = False
        self.Settings[4] = 0x04
        self.Settings[5] = 0x00
        self.Settings[6] = 0x84
        self.Settings[7] = 0x80 + self.Volume
        self.Settings = self.Settings[:8]
        
    def ProgramRadio(self):
        self.UpdateSettings()
        self.radio_i2c.writeto(self.i2c_device_address, self.Settings)

# ----------------------------------------------------
# CORE 1: DEDICATED SCREEN THREAD LOOP
# ----------------------------------------------------
def display_core_thread():
    global UpdateDisplay, Count
    
    # Initialize Core-isolated SPI Hardware interface
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
        # Check flag from encoder updates
        if UpdateDisplay:
            UpdateDisplay = False # Reset immediately
            
            oled.clear_buffers()
            
            # Text UI layout elements
            oled.draw_text8x8(0, 0, "Clock Radio") 
            oled.draw_text8x8(0, 30, "Freq: %5.1f MHz" % fm_radio.Frequency)
            oled.draw_text8x8(0, 40, "Volume: %2d / 15" % Count) 
            
            # Dynamic Volume Progress Bar Logic
            # Scale the volume max (15) to full display width pixel canvas (128)
            bar_width = int((Count / 15) * 128)
            oled.draw_rectangle(0, 55, bar_width, 5)        

            # Ship buffer over to physical display panel
            oled.present()
            
        # Yield core slice back to prevent hardware resource starvation
        time.sleep_ms(15)

# ----------------------------------------------------
# MAIN SYSTEM INITIALIZATION (CORE 0 STARTUP)
# ----------------------------------------------------

# 1. Start the Radio instance on I2C
fm_radio = Radio(98.5, 2, False)

# 2. Attach Pin Interruption Hooks (Soft execution context via hard=False)
EncoderA.irq(handler=VolumeEncoderInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=False)
EncoderB.irq(handler=VolumeEncoderInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=False)

# 3. Fire up Core 1 for dedicated layout drawing operations
_thread.start_new_thread(display_core_thread, ())

# 4. Core 0 Main Thread Loop
while True:
    # Core 0 remains free. Interrupt handles background I2C radio updates instantly.
    time.sleep(1)