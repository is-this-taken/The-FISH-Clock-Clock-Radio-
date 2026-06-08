# encoder_method1.py
# SSD1309 version

from machine import Pin, SPI

# CHANGED: SSD1306 -> SSD1309 Display driver
from ssd1309 import Display

SCREEN_WIDTH  = 128
SCREEN_HEIGHT = 64

#
# 2D lookup table indexed by [previous AB][current AB].
#
table = [
    [ 0, -1, +1,  0],  # previous AB = 00
    [+1,  0,  0, -1],  # previous AB = 01
    [-1,  0,  0, +1],  # previous AB = 10
    [ 0, +1, -1,  0],  # previous AB = 11
]

#
# Encoder inputs
#
EncoderA = Pin(4, Pin.IN)
EncoderB = Pin(2, Pin.IN)

#
# Global state
#
Count         = 50
UpdateDisplay = True
PrevAB        = (EncoderA.value() << 1) | EncoderB.value()

#
# Interrupt handler
#
def EncoderInterrupt(pin):
    global Count, UpdateDisplay, PrevAB

    curr = (EncoderA.value() << 1) | EncoderB.value()
    delta = table[PrevAB][curr]
    PrevAB = curr

    if delta == +1 and Count < 99:
        Count += 1
        UpdateDisplay = True

    elif delta == -1 and Count > 0:
        Count -= 1
        UpdateDisplay = True


#
# Encoder interrupts
#
EncoderA.irq(
    handler=EncoderInterrupt,
    trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING,
    hard=True
)

EncoderB.irq(
    handler=EncoderInterrupt,
    trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING,
    hard=True
)

# ----------------------------------------------------
# DISPLAY SETUP
# ----------------------------------------------------

spi_sck = Pin(18)
spi_sda = Pin(19)
spi_res = Pin(21)
spi_dc  = Pin(20)
spi_cs  = Pin(17)

SPI_DEVICE = 0

# CHANGED: faster SPI
oled_spi = SPI(
    SPI_DEVICE,
    baudrate=1000000,
    sck=spi_sck,
    mosi=spi_sda
)


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

    if UpdateDisplay == True:

        UpdateDisplay = False

     
        oled.clear_buffers()

       
        oled.draw_text8x8(0, 0, "Welcome to ECE")
        oled.draw_text8x8(45, 10, "299")
        oled.draw_text8x8(0, 30, "Count is: %4d" % Count)

       
        oled.draw_rectangle(0, 50, 128, 5)

     
        oled.present()

