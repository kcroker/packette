#!/usr/bin/python3

import argparse
import multiprocessing
from os import kill
from signal import SIGINT
from sys import stderr

import lappdIfc

#
# Common parameters that are used by anything intaking packets
#
def create(leader):
    
    parser = argparse.ArgumentParser(description=leader)
    
    parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')

    parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Upload a pedestal for firmware subtraction')
    parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, default=1338, help='Aim the board at this port on this machine.')
    parser.add_argument('-c', '--channels', metavar='CHANNELS', help="Explicitly force the channel mask. (Persistent)")
    parser.add_argument('-w', '--wait', metavar='WAIT', type=int, help="Adjust delay between receipt of soft/hard trigger and DRS4 sampling stop. (Persistant)")

    parser.add_argument('-N', metavar='NUM_SAMPLES', type=int, default=0, help='Issue N soft triggers of the board')
    parser.add_argument('-i', metavar='INTERVAL', type=float, default=0.001, help='The interval (seconds) between software triggers')
    parser.add_argument('-I', '--initialize', action="store_true", help="Initialize the board")
    parser.add_argument('-T', '--threads', metavar="NUM_THREADS", type=int, help="Number of distinct ports to receive data.  Ports increment from the aimed port.", default=1)

    parser.add_argument('-e', '--external', action="store_true", help='Toggle hardware triggering.')
    parser.add_argument('-z', '--zero-suppress', action="store_true", help='Toggle firmware zero suppression')
    parser.add_argument('-O', '--oscillator', action="store_true", help='Toggle TCAL input between calibration signal and external analog SMA')
    
    # At these values, unbuffered TCAL does not
    # have the periodic pulse artifact (@ CMOFS 0.8)
    #
    # Note that in A21, CMOFS is tied to OOFS, so you can't change that one without
    # undoing the effect on the other side of teh DRS4s
    #
    # DAC probably cares about OOFS being in a good spot... is it?
    # As per DRS4 spec, 1.55V gives symmetric
    # differential inputs of -0.5V to 0.5V.
    # Set the non-swept values
    # For both sides of the DRS rows

    parser.add_argument('--oofs', metavar='OOFS', type=float, default=0.0, help='OOFS DAC output voltage')
    parser.add_argument('--rofs', metavar='ROFS', type=float, default=1.05, help='ROFS DAC output voltage')
    parser.add_argument('--tcal', metavar='TCAL', type=float, default=1.05, help='Start values for TCAL_N1 and TCAL_N2 DAC output voltage')
    parser.add_argument('--cmofs', metavar='CMOFS', type=float, default=1.2, help='CMOFS DAC output Voltage')
    parser.add_argument('--bias', metavar='BIAS', type=float, default=0.7, help='BIAS DAC output Voltage') #usually 0.7
    
    return parser

# DAC Channel mappings (in A21 crosshacked)
# (these should be moved to lappdIfc.py)
DAC_BIAS = 0
DAC_ROFS = 1
DAC_OOFS = 2
DAC_CMOFS = 3
DAC_TCAL_N1 = 4
DAC_TCAL_N2 = 5

ifc = None

def connect(parser):

    global ifc
    
    # Parse the arguments
    args = parser.parse_args()

    # Connect to the board
    ifc = lappdIfc.lappdInterface(args.board)

    # Initialize the board, if requested
    if args.initialize:
        ifc.Initialize()

    # Set the requested threads on the hardware side 
    ifc.brd.pokenow(lappdIfc.NUDPPORTS, args.threads)

    # Give the socket address for use by spawn()
    ifc.brd.aimNBIC(port=args.aim)
    args.listen = ifc.brd.s.getsockname()[0]

    # Set DAC voltages
    ifc.DacSetVout(DAC_OOFS, args.oofs)
    ifc.DacSetVout(DAC_CMOFS, args.cmofs)
    ifc.DacSetVout(DAC_ROFS, args.rofs)
    ifc.DacSetVout(DAC_BIAS, args.bias)
    ifc.DacSetVout(DAC_TCAL_N1, args.tcal)
    ifc.DacSetVout(DAC_TCAL_N2, args.tcal)

    # Set the channels?
    if args.channels:
        chans = list(map(int, args.channels.split()))
        print("Specifying channels: ", chans, file=stderr)

        high = 0
        low = 0
        for chan in chans:
            if chan < 32:
                low |= (1 << chan)
            else:
                high |= (1 << (chan - 32))

        ifc.brd.pokenow(0x670, low)
        ifc.brd.pokenow(0x674, high)

    # Set the wait?
    if args.wait:
        ifc.brd.pokenow(lappdIfc.DRSWAITSTART, args.wait)
        print("Setting STOP delay to: %d" % args.wait, file=stderr)

    # Enable the external trigger if it was requested
    if args.external:
        mysteryReg = ifc.brd.peeknow(0x370)
        ifc.brd.pokenow(0x370, mysteryReg | (1 << 5))

   # Return a tuble with the interface and the arguments
    return (ifc, args)

#
#
# 
#
def disableTCAL(ifc):

    # Disable OUT4 (TCAL_N1)
    ifc.brd.pokenow(0x1000 | (0x3 << 2), 0x10)
