##  Thing Magic M5e and M5e-Compact Python Interface
##  Written by Travis Deyle [tdeyle@gatech.edu] under the tutelage of 
##    Dr. Matt Reynolds (Duke University) and Dr. Charlie Kemp (Georgia Tech)
##    Please remember me if you become rich and/or famous, and please  
##    refer to our related work(s) when writing papers.  Thanks.

import sys, serial, time
from threading import Thread
from time import time


# This class is more general in that it allows custum antenna functions (if
# using custom hardware) in addition to callbacks (such as the ROS publish)

class M5e_Poller(Thread):
    QUERY_MODE = 'query'
    TRACK_MODE = 'track'

    def __init__(self, M5e, antfuncs=[], callbacks=[]):
        Thread.__init__(self)
        self.M5e = M5e
        self.antfuncs = antfuncs
        self.callbacks = callbacks
        self.mode = ''
        self.should_run = True
        
        print 'Creating M5e Polling Thread'
        self.start()
        #print 'I was made!'

    def pause_poller(self):
        self.mode = ''

    def query_mode(self):
        self.mode = self.QUERY_MODE

    def track_mode(self, tag_id):
        self.mode         = self.TRACK_MODE
        self.tag_to_track = tag_id
    
    def broadcast_ROS(self):
        import rfid.M5e_ROS as M5e_ROS
        self.broadcaster = M5e_ROS.Broadcast_M5e_ROS(self)
        self.callbacks.append( broadcaster.broadcast )

    def run(self):
        while self.should_run:
            if self.mode == self.QUERY_MODE:
                for aF in self.antfuncs:
                    antennaName = aF(self.M5e)    # let current antFunc make appropriate changes
                    results = self.M5e.QueryEnvironment()
                    for tagid, rssi in results:
                        datum = [antennaName, tagid, rssi]
                        [cF(datum) for cF in self.callbacks]
            elif self.mode == self.TRACK_MODE:
                for aF in self.antfuncs:
                    antennaName = aF(self.M5e)    # let current antFunc make appropriate changes
                    tagid = self.tag_to_track
                    rssi = self.M5e.TrackSingleTag(tagid)
                    if rssi != -1:
                        datum = [antennaName, tagid, rssi]
                        [cF(datum) for cF in self.callbacks]
            else:
                time.sleep(0.005)
        
    def stop(self):
        self.should_run = False
        self.join(3)
        if (self.isAlive()): 
            raise RuntimeError("RFID M5e Poller: unable to stop thread")
    
class M5e:
    "Interface to Mercury M5e and M5e-Compact"
    def __init__(self, portINT=-1, portSTR='/dev/robot/RFIDreader', baudrate=9600, 
        TXport=1, RXport=1, readPwr=2300, protocol='GEN2', compact=True, verbosity=1):
        if portINT != -1:
            self.port = portINT	# stores the serial port as 0-based integer
        else:
            self.port = portSTR	# stores it as a /dev-mapped string
        
        self.baudrate = baudrate    # should be 9600 for M5e by default.  May want to up the baud for faster reading (after bootup)
        self.TXport = TXport        # Initialized transmit antenna
        self.RXport = RXport        # Initialized receive antenna
        self.readPwr = readPwr      # Initialized read TX power in centi-dBm
        self.protocol = protocol    # Initialized protocol
        self.compact = compact
        self.verbosity = verbosity
        self.ser = None
        
        if verbosity > 0:
            print 'Initializing M5e (or M5e-Compact)'
        
        # Setup Serial port  (kinda Hacky, but it works and I don't want to waste time on it)
        #    Read/Write timeouts should be appropriate for data sizes being dealt with.  Keep this in mind
        
        failed = False
        try:
            print '\tAttempting 230400 bps'
            self.ser = serial.Serial(self.port, 230400, timeout=2, writeTimeout=2)
            # Check if BootLoader is running by issuing "Get BootLoader/Firmware Version"        
            self.TransmitCommand('\x00\x03')
            self.ReceiveResponse()      # automatically makes sure returned status = 0x0000
            print '\tSuccessful at 230400 bps'
        except:
            self.ser = None
            failed = True
            print '\tFailed @ 230400 bps'
            pass
        
        if failed:
            print '\tAttempting 9600 bps'
            try:
                self.ser = serial.Serial(self.port, 9600, timeout=2, writeTimeout=2)
                self.TransmitCommand('\x00\x03')
                self.ReceiveResponse()      # automatically makes sure returned status = 0x0000
                print '\tSuccessful @ 9600 bps'
            except:
                print '\tFailed 9600 bps'
                self.ser = None
                raise M5e_SerialPortError('Could not open serial port %d at baudrate %d or %d.' % (self.port,230400,9600))
            
            # Change baud to 230400 bps (instead of 9600 default)
            print '\tSwitching to 230400 bps'
            self.TransmitCommand('\x04\x06\x00\x03\x84\x00')
            self.ReceiveResponse()    
            self.ser = None
            try:
                print '\tAttempting to reconnect @ 230400 bps'
                self.ser = serial.Serial(self.port, 230400, timeout=2, writeTimeout=2)
                # Check if BootLoader is running by issuing "Get BootLoader/Firmware Version"        
                self.TransmitCommand('\x00\x03')
                self.ReceiveResponse()      # automatically makes sure returned status = 0x0000
                print '\tSuccessfully reconnected at 230400 bps'
            except:
                self.ser = None
                print '\tFailed @ 230400 bps'
                pass
        
        if self.ser == None:
            raise M5e_SerialPortError('Could not open serial port %d at baudrate %d or %d.' % (self.port,230400,9600))
        
        # Check if BootLoader is running by issuing "Get BootLoader/Firmware Version"        
        self.TransmitCommand('\x00\x03')
        self.ReceiveResponse()      # automatically makes sure returned status = 0x0000
        
        # Boot into Firmware
        self.TransmitCommand('\x00\x04')
        try:
            self.ReceiveResponse()
        except M5e_CommandStatusError, inst:
            # Non-Zero Response will be received if the reader has already booted into firmware
            #   This occurs when you've already powered-up & previously configured the reader.  
            #   Can safely ignore this problem and continue initialization
                if inst[1] == '\x01\x01':       # This actually means "invalid opcode"
                    pass
                else:
                    raise
        
        self.ChangeAntennaPorts(self.TXport, self.RXport)
        self.ChangeTXReadPower(self.readPwr)
                
        # Set Current Tag Protocol to GEN2
        if self.protocol != 'GEN2':
            raise M5e_error('Sorry, GEN2 is only protocol supported at this time')
        self.TransmitCommand('\x02\x93\x00\x05')
        self.ReceiveResponse()
        
        # Set Region (we're only going to deal with North America)
        self.TransmitCommand('\x01\x97\x01')
        self.ReceiveResponse()
        
        # Set Power Mode (we'll just use default of "full power mode").
        # Use remaining defaults
        
        
        
    def ChangeAntennaPorts(self, TXport, RXport):
        "Changes TX and RX ports"
        self.TXport = TXport
        self.RXport = RXport
        self.TransmitCommand('\x02\x91' + chr(self.TXport) + chr(self.RXport))
        self.ReceiveResponse()
        
    def ChangeTXReadPower(self, readPwr):
        "Sets the Read TX Power based on current value of readPwr (in centi-dBm)"
        self.readPwr = readPwr
        readTXPwrHighByte = chr((self.readPwr & 0xFFFF) >> 8)
        readTXPwrLowByte = chr(self.readPwr & 0x00FF)
        self.TransmitCommand('\x02\x92'+ readTXPwrHighByte + readTXPwrLowByte)
        self.ReceiveResponse()
        
    def CalculateCRC(self, msg):
        "Implements CCITT CRC-16 defined in Mercury Embedded Module Dev Guide."
        crcResult = 0xFFFF
        for x in range(len(msg)):
            currChar = ord(msg[x])
            v = 0x80
            for y in range(8):
                xor_flag = 0
                if (crcResult & 0x8000):
                    xor_flag = 1
                crcResult = crcResult << 1
                if (currChar & v):
                    crcResult = crcResult + 1
                if (xor_flag):
                    crcResult = crcResult ^ 0x1021
                v = v >> 1
                crcResult = crcResult & 0xFFFF
            #print hex(currChar)
        return chr((crcResult >> 8) & 0xFF) + chr(crcResult & 0xFF)
        # return the 16-bit result in the form of 2 characters

    def ReturnHexString(self, hexStr):
        "Helper function to visualize a hex string (such as a hexCommand)"
        result = ''
        for i in range(len(hexStr)):
            result = result + hex(ord(hexStr[i])) + ' '
        return result

    def ConstructCommand(self, hexCommand):
        "Helper function to attach start byte and CRC to a command string"
        return '\xFF' + hexCommand + self.CalculateCRC(hexCommand)

    def TransmitCommand(self, command):
        "Transmits a command.  Should call ReceiveResponse before calling again."
        try:
            self.ser.write(self.ConstructCommand(command))
        except:
            raise M5e_TransmitTimeoutExceeded('Something happened (probably power failure) to disable serial transmission')
        
    def ReceiveResponse(self):
        "Receives a single command's response"
        # Get Start byte, disregard anything else...
        timeoutsToWait = 5
        timeoutsWaited = 0

        while timeoutsWaited < timeoutsToWait:
            start = self.ser.read()	    # this is non-blocking.  Will wait for timeout duration, then return
            if start == '\xFF':
                break
            timeoutsWaited += 1
            
        if start != '\xFF':
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (start byte).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')
            
        length = self.ser.read()        # non blocking, returns after timeout
        if len(length) != 1:
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (length byte).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')

        command = self.ser.read()
        if len(command) != 1:
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (command byte).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')

        status = self.ser.read(2)       # non-blocking
        if len(status) != 2:
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (status bytes).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')

        data = self.ser.read(ord(length))
        if len(data) != ord(length):
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (data bytes).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')

        CRC = self.ser.read(2)
        if len(CRC) != 2:
            time.sleep(5)
            self.ser.flushInput()
            raise M5e_ReceiveError('Error in receive stream (CRC bytes).  Waited 5 seconds then flushed input.  Try reissueing command and receive response.')
        
        # Validate the CRC
        validateCRC = length + command + status + data
        if self.CalculateCRC(validateCRC) != CRC:
            raise M5e_CRCError('Received response CRC failed')
        
        # Check if return status was OK (0x0000 is success)
        if status != '\x00\x00':
            raise M5e_CommandStatusError('Received response returned non-zero status',status)
            
        return (start, length, command, status, data, CRC)
        
    def QueryEnvironment(self, timeout=50):
        # Read Tag ID Multiple
        timeoutHighByte = chr((timeout & 0xFFFF) >> 8)
        timeoutLowByte = chr(timeout & 0x00FF)
        try:
            self.TransmitCommand('\x04\x22\x00\x00'+timeoutHighByte+timeoutLowByte)
            self.ReceiveResponse()
        except M5e_CommandStatusError, inst:
            flag = False
            # Read & Get returns non-zero status when no tags found.  This is 
            #   an expected event... so ignore the exception.
            if inst[1] == '\x04\x00':   
                return []
            else:
                raise

        # Get Tag Buffer
        #   Get # Tags remaining
        self.TransmitCommand('\x00\x29')
        (start, length, command, status, data, CRC) = self.ReceiveResponse()
        
        readIndex = (ord(data[0]) << 8) + ord(data[1])
        writeIndex = (ord(data[2]) << 8) + ord(data[3])
        numTags = writeIndex - readIndex
        
#         tagEPCs = []
#         while numTags > 0:
#             numFetch = min([numTags, 13])
#             numFetchHighByte = chr((numFetch & 0xFFFF) >> 8)
#             numFetchLowByte = chr(numFetch & 0x00FF)
#             self.TransmitCommand('\x02\x29' + numFetchHighByte + numFetchLowByte)
#             (start, length, command, status, data, CRC) = self.ReceiveResponse()
            
#             # each tag occupies 18 bytes in the response, regardless of tag size
#             for i in range(numFetch): # NOTE: first 4 bytes in GEN2 are size & protocol.  Last 2 are CRC
#                 tagEPCs.append(data[i*18+4:(i+1)*18-2])
#                 #tagEPCs.append(data[i*18:(i+1)*18])
            
#             numTags = numTags - numFetch

        results = []   # stored as (ID, RSSI)
        while numTags > 0:
            self.TransmitCommand('\x03\x29\x00\x02\x00')
            (start, length, command, status, data, CRC) = self.ReceiveResponse()

            tagsRetrieved = ord(data[3])
            for i in xrange(tagsRetrieved):
                rssi = ord(data[4 + i*19])
                tagID = data[4 + i*19 + 5 : 4 + i*19 + 5 + 12]
                results.append( (tagID, rssi) )
            
            numTags = numTags - tagsRetrieved
            
        # Reset/Clear the Tag ID Buffer for next Read Tag ID Multiple
        self.TransmitCommand('\x00\x2A')
        self.ReceiveResponse()
            
        return results
    
    def TrackSingleTag(self, tagID, timeout=50):
        # Make sure TagID is 60-bits
        if len(tagID) != 12:
            raise M5e_Error('Only 96-bit tags supported by TrackSingleTag')
        
        timeoutHighByte = chr((timeout & 0xFFFF) >> 8)
        timeoutLowByte = chr(timeout & 0x00FF)
        try:
            self.TransmitCommand('\x12\x21'+timeoutHighByte+timeoutLowByte+'\x11\x00\x02\x60'+tagID)
            (start, length, command, status, data, CRC) = self.ReceiveResponse()
            # data is in form OptionsFlags (1 byte) MetaFlags (2 bytes) RSSI (1 byte), EPC (12 bytes data[-14:-2]) TAG CRC (2 bytes)
        except M5e_CommandStatusError, inst:
            flag = False
            # Read & Get returns non-zero status when no tags found.  This is 
            #   an expected event... so ignore the exception.
            if inst[1] == '\x04\x00':   
                return -1   # Requested tag not found
            else:
                raise
            
        return ord(data[3])

    def ChangeTagID(self, newTagID, timeout=50):
        # Note: This will rewrite the EPC on the first tag detected!
        
        # Make sure TagID is 60-bits
        if len(newTagID) != 12:
            raise M5e_Error('Only 96-bit tags supported by TrackSingleTag')
        
        timeoutHighByte = chr((timeout & 0xFFFF) >> 8)
        timeoutLowByte = chr(timeout & 0x00FF)
        try:
            cmdLen = chr(len(newTagID)+4)
            self.TransmitCommand(cmdLen+'\x23'+timeoutHighByte+timeoutLowByte+'\x00\x00'+newTagID)
            (start, length, command, status, data, CRC) = self.ReceiveResponse()
        except M5e_CommandStatusError, inst:
            return False
            
        return True
    
    def QuickQuery(self):
        #prints data to a log file once
        while True:
            try:
                logname = str(raw_input("Please enter the name of the target log file: "))
                break
            except IOError:
                print "The logfile name must be valid."
        
        path = '/home/tbg4/Desktop/hospirfidbot/logs/' + logname
        f = file(path, 'w')     #this line and the next generate the log file
        f.close()
        t = str(time())
        data = self.QueryEnvironment()
        print t
        print data
        f = open(path, 'r+')     # this method does not handle exceptions
        f.seek(0, 2)
        f.write(t)
        for i in data:
            a1, a2 = i
            f.write(' ' + a1.encode("hex") + ' ' + str(a2))
        f.write('\n')
        f.close()
        del data
        
    def LoopQuery(self):
        #indefinitely prints data to a log file
        while True:
            try:
                logname = str(raw_input("Please enter the name of a new log file: "))
                break
            except IOError:
                print "The logfile name must be valid."
        
        path = '/home/tbg4/Desktop/hospirfidbot/logs/' + logname
        f = file(path, 'w')     #this line and the next generate the log file
        f.close()
        while 1:
            t = str(time())
            data = self.QueryEnvironment()
            print t
            print data
            with open(path, 'r+') as f:    # this method handles exceptions (supposedly)
                f.seek(0, 2)
                f.write(t + ' ' + str(len(data)))
                for i in data:
                   a1, a2 = i
                   f.write(' ' + a1.encode("hex") + ' ' + str(a2))
                f.write('\n')
                f.close()
         #   f = open(path, 'r+')     # this method does not handle exceptions
         #   f.seek(0, 2)
         #   f.write(t)
         #   for i in data:
         #       a1, a2 = i
         #       f.write(' ' + str(a1) + ' ' + str(a2))
         #   f.write('\n')
         #   f.close()
            del data
        return

class M5e_error(Exception):
    "General Exception"
    pass

class M5e_SerialPortError(M5e_error):
    "If pyserial throws error"
    pass
    
class M5e_CRCError(M5e_error):
    "If CRC check from Mercury packet is incorrect (data corruption)"
    pass
    
class M5e_CommandStatusError(M5e_error):
    "If return response from Mercury is non-zero (error status)"
    pass

class M5e_TransmitTimeoutExceeded(M5e_error):
    "Something happened (probably power failure) to disable serial transmission"
    pass

class M5e_ReceiveError(M5e_error):
    "Serial input out of synch.  Try waiting a few seconds, flush input stream, and reissue command"
    pass


## THIS IS THE "DIRECT" METHOD...
##if __name__ == '__main__':
##    import time
##    import numpy as np
##    
##    read = M5e(portSTR='/dev/ttyUSB0', baudrate=230400)   
##
##    # Demonstrate Querying the environment
##    for i in range(5):
##        print read.QueryEnvironment()
##        time.sleep(1)
##        
##    # To track tags' RSSI
##    tags = read.QueryEnvironment()
##    for tag in tags:
##        print [tag], read.TrackSingleTag(tag)


## METHOD USING THREADS (more generally useful)
if __name__ == '__main__':
    import time
    
    def P1(M5e):
        M5e.ChangeAntennaPorts(1,1)
        return 'AntPort1'

    def P2(M5e):
        M5e.ChangeAntennaPorts(2,2)
        return 'AntPort2'

    def PrintDatum(data):
        ant, ids, rssi = data
        print data

    r = M5e(readPwr=3000)
    q = M5e_Poller(r, antfuncs=[P1, P2], callbacks=[PrintDatum])

    q.query_mode()
    
    t0 = time.time()
    while time.time() - t0 < 3.0:
        blah = 0

    q.track_mode('RedBottle   ')

    t0 = time.time()
    while time.time() - t0 < 3.0:
        blah = 0

    q.stop()
