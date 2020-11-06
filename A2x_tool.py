#!/usr/bin/python3
import sys
import os

import pickle
import queue
import socket
import time

import A2x_common
import lappdIfc


# Make a new tool
parser = A2x_common.create('Generic configuration tool for Ultralytics A2x series LAPPD boards.')

# Custom args
parser.add_argument('-R', '--register', dest='registers', metavar='REGISTER', type=str, nargs=1, action='append', help='Peek and document the given register')
parser.add_argument('-W', '--words', metavar='NUM_WORDS', type=int, help='Number of samples to report after DRS4 stop. (must be power of 2 for packette)')

# Connect to the board
ifc, args = A2x_common.connect(parser)

# Simple sanity check
if args.r < 0:
    raise Exception("Rate must be positive")
    
# Are we using an external trigger?  If so, kill the delay
if args.external:
    args.i = 0
        
# Record a bunch of registers first
# (Abhorrent magic numbers...)

# Take the voltages we care about.
#
# From Vasily's snippet
#           dacCode = int(0xffff/2.5*VOut)
# So inverting it:
#   VOut = 0xfff/(2.5*dacCode)
#
human_readable = {
    0 : 'bias',
    1 : 'rofs',
    2 : 'oofs',
    3 : 'cmofs',
    4 : 'tcal_n1',
    5 : 'tcal_n2'
}
    
human_readable = {
    lappdIfc.DRSREFCLKRATIO : 'DRSREFCLKRATIO',
    lappdIfc.ADCBUFNUMWORDS : 'ADCBUFNUMWORDS',
    0x620 : '36 + 4*(selected oversample)'
}

if args.words:
    ifc.brd.pokenow(lappdIfc.ADCBUFNUMWORDS, int(args.words))

for reg in [lappdIfc.DRSREFCLKRATIO, 0x620, lappdIfc.ADCBUFNUMWORDS]:
    val = ifc.brd.peeknow(reg)
    print("#\t%s (%s) = %d" % (human_readable[reg], hex(reg), val))

# Make it pretty
print("#")

# Turn on the external trigger, if it was requested and its off
triggerToggled = False
        
events = []
import time

# If we are using external triggers, be done
if args.external:
    exit(0)
        
# Otherwise, send soft triggers
for i in range(0, args.N):
    # Suppress board readback and response!
    ifc.brd.pokenow(0x320, (1 << 6), readback=False, silent=True)
    
    # Notify that a trigger was sent
    # print("Trigger %d sent..." % i, file=sys.stderr)
    
    # Sleep for the specified delay
    time.sleep(1.0/args.r)
