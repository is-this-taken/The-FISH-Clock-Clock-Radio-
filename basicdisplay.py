from machine import Pin, SPI 

# Import the custom SSD1309 driver class
from ssd1309 import Display
import framebuf 

# Define columns and rows of the OLED display
SCREEN_WIDTH = 128 
SCREEN_HEIGHT = 64 

# Initialize I/O pins associated with the OLED display SPI interface
spi_sck = Pin(18) 
spi_sda = Pin(19) # MOSI / TX pin
spi_res = Pin(21) # Reset pin
spi_dc  = Pin(20) # Data/Command pin
spi_cs  = Pin(17) # Chip Select pin

SPI_DEVICE = 0 

# Initialize the SPI interface
oled_spi = SPI(SPI_DEVICE, baudrate=1000000, sck=spi_sck, mosi=spi_sda)

# Initialize the display using the driver's constructor parameters
oled = Display(
    spi=oled_spi, 
    cs=spi_cs, 
    dc=spi_dc, 
    rst=spi_res, 
    width=SCREEN_WIDTH, 
    height=SCREEN_HEIGHT, 
    flip=False
)

# Assign a value to a variable
Count = 3113

while True:
    # Clear the frame buffer
    oled.clear_buffers()
        
    # Update the text on the screen using the driver's built-in 8x8 font method
    oled.draw_text8x8(0, 0, "Welcome to ECE") 
    oled.draw_text8x8(45, 10, "299") 
    oled.draw_text8x8(0, 30, "Count is: %4d" % Count) 
        
    # Draw box below the text using the custom rectangle method
    oled.draw_rectangle(0, 50, 128, 5)        

    # Transfer the buffer data to the physical screen
    oled.present()