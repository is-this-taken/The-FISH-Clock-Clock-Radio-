from machine import Pin, SPI # SPI is a class associated with the machine library. 


# The below specified libraries have to be included. Also, ssd1306.py must be saved on the Pico. 
from ssd1306 import SSD1306_SPI # this is the driver library and the corresponding class
import framebuf # this is another library for the display. 


# Define columns and rows of the oled display. These numbers are the standard values. 
SCREEN_WIDTH = 128 #number of columns
SCREEN_HEIGHT = 64 #number of rows

EncoderState = 0
UpdateDisplay = True

#
# Encoder service routine for terminal A and B
#

def DoEncoder( Encoder, State ):
    global EncoderState
    global Count
    global UpdateDisplay

#
# Debug output
#
#    print( EncoderState, Encoder, State )

    if ( EncoderState == 0 ):
#
# Check for input A going low ( encoder turning left )
#
        if (( Encoder == 'A' ) and ( State == 4 )):
            EncoderState = 1

#
# Check for input B going low ( encoder turning right )
#
        if (( Encoder == 'B' ) and ( State == 4 )):
            EncoderState = 4

#
# Encoding turing right squence ( A=0 then B=0 then A=1 and finally B=1 )
#

    elif( EncoderState == 1 ):
#        
# This should be input B going low
#
        if (( Encoder == 'B' ) and ( State == 4 )):
            EncoderState = 2
        else:
            EncoderState = 0
            
    elif ( EncoderState == 2 ):
#
# This should be input A going high
#        
        if (( Encoder == 'A' ) and ( State == 8 )):
            EncoderState = 3
        else:
            EncoderState = 0
            
    elif ( EncoderState == 3 ):
#
# Finally input B should go high
#
        if (( Encoder == 'B' ) and ( State == 8 )):

#
# The shaft is turing right so increment the count
#            
            if ( Count < 99 ):
                Count = Count + 1
                UpdateDisplay = True

               
        EncoderState = 0


#
# Encoding turing left squence ( B=0 then A=0 then B=1 and finally A=1 )
#

    elif ( EncoderState == 4 ):
#        
# This should be input A going low
#        
        if (( Encoder == 'A' ) and ( State == 4 )):
            EncoderState = 5
        else:
            EncoderState = 0
            
    elif ( EncoderState == 5 ):
#        
# This should be input B going high
#        
        if (( Encoder == 'B' ) and ( State == 8 )):
            EncoderState = 6
        else:
            EncoderState = 0
                        
    elif ( EncoderState == 6 ):
#        
# This should be input A going high
#        
        if (( Encoder == 'A' ) and ( State == 8 )):
#
# The shaft is turing left so decrement the count
#
            if ( Count != 0 ):
                Count = Count - 1
                UpdateDisplay = True

        EncoderState = 0

    else:
        EncoderState = 0
            
    return( True )

#
# Service terminal A interrupt
#

def EncoderAInterrupt( Pin ):
    DoEncoder( 'A', Pin.irq().flags())
    return( True )

#
# Service terminal B interrupt
#

def EncoderBInterrupt( Pin ):
    DoEncoder( 'B', Pin.irq().flags())
    return( True )

#
# GPIO 4 ( Pin 6 ) is connected to terminal A on the encoder
#
EncoderA = Pin( 4, Pin.IN )

#
# GPIO 2 ( Pin 4 ) is connected to terminal B on the encoder
#

EncoderB = Pin( 2, Pin.IN )

#
# Enable interrupt detection for both rising and falling edges of both signals
#

EncoderA.irq( handler= EncoderAInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=True )
EncoderB.irq( handler= EncoderBInterrupt, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=True )




# Initialize I/O pins associated with the oled display SPI interface

spi_sck = Pin(18) # sck stands for serial clock; always be connected to SPI SCK pin of the Pico
spi_sda = Pin(19) # sda stands for serial data;  always be connected to SPI TX pin of the Pico; this is the MOSI
spi_res = Pin(21) # res stands for reset; to be connected to a free GPIO pin
spi_dc  = Pin(20) # dc stands for data/command; to be connected to a free GPIO pin
spi_cs  = Pin(17) # chip select; to be connected to the SPI chip select of the Pico 

#
# SPI Device ID can be 0 or 1. It must match the wiring. 
#
SPI_DEVICE = 0 # Because the peripheral is connected to SPI 0 hardware lines of the Pico

#
# initialize the SPI interface for the OLED display
#
oled_spi = SPI( SPI_DEVICE, baudrate= 100000, sck= spi_sck, mosi= spi_sda )

#
# Initialize the display
#
oled = SSD1306_SPI( SCREEN_WIDTH, SCREEN_HEIGHT, oled_spi, spi_dc, spi_res, spi_cs, True )


# Assign a value to a variable
Count = 50

while ( True ):

        if ( UpdateDisplay == True ):
            
            UpdateDisplay = False
#
# Clear the buffer
#
            oled.fill(0)
        
#
# Update the text on the screen
#
            oled.text("Welcome to ECE", 0, 0) # Print the text starting from 0th column and 0th row
            oled.text("299", 45, 10) # Print the number 299 starting at 45th column and 10th row
            oled.text("Count is: %4d" % Count, 0, 30 ) # Print the value stored in the variable Count. 
        
#
# Draw box below the text
#
            oled.rect( 0, 50, 128, 5, 1  )        

#
# Transfer the buffer to the screen
#
            oled.show()
    
