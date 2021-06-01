#!/usr/bin/python3

import argparse
import multiprocessing
from os import kill,environ
from signal import SIGINT
import sys

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
environ['EEVEE_SRC_PATH'] = "./eevee"

import lappdIfc

#
# Common parameters that are used by anything intaking packets
#
def create(leader):
    
    parser = argparse.ArgumentParser(description=leader)
    
    parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')

    parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Upload a pedestal for firmware subtraction')
    parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, help='Aim the board at this port on this machine.')
    parser.add_argument('-c', '--channels', metavar='CHANNELS', help="Explicitly force a hex channel mask. (Persistent)")
    parser.add_argument('-w', '--wait', metavar='WAIT', type=int, help="Adjust delay between receipt of soft/hard trigger and DRS4 sampling stop. (Persistant)")
    parser.add_argument('-u', '--udpsport', metavar='UDPSPORT', type=int, help="Set the originating port for outgoing control signals explicitly")
    
    parser.add_argument('-N', metavar='NUM_SAMPLES', type=int, default=0, help='Issue N soft triggers of the board')
    parser.add_argument('-r', metavar='RATE', type=float, default=100, help='The rate (in Hz) of software triggers')
    parser.add_argument('-I', '--initialize', action="store_true", help="Initialize the board")
    parser.add_argument('-t', '--threads', metavar="NUM_THREADS", type=int, help="Number of distinct ports to receive data.  Ports increment from the aimed port.", default=1)

    parser.add_argument('-e', '--external', type=int, help='Adjust extriggering (odd is on)')
    parser.add_argument('-p', '--pedestal', type=int, help='Adjust hardware pedestal subtraction (odd is on)')
    parser.add_argument('-z', '--zsuppress', type=int, help='Adjust firmware zero channel suppression (odd is on)')
    parser.add_argument('-O', '--oscillator', type=int, help='Adjust internal 100Mhz oscillator on all TCAL lines (odd is on)')
    parser.add_argument('--adcmode', type=str, help='Put the ADC into alternate modes for debugging')
    
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

    # This is getting outputs, but maybe fucking the ADCs hard...
    #parser.add_argument('--oofs', metavar='OOFS', type=float, default=1.3, help='DC offset for DRS4 output into ADC (OOFS)') #?/

    # KC 5/29/21
    # PRevious defauilts
    # 1.15, 0.8, 0.8, 0.7, 1.55
    
    # Manual iteration tests seem to show that 1.25 outperforms 1.2 by factors of 2-3x in most places
    parser.add_argument('--oofs', metavar='OOFS', type=float, help='DC offset for DRS4 output into ADC (OOFS)') #?/
    parser.add_argument('--cmofs', metavar='CMOFS', type=float, help='DC offset into DRS4 (DRS4 wants 0.1 - 1.5V) (CMOFS)')
    parser.add_argument('--tcal', metavar='TCAL', type=float, help='DC offset for the calibration lines TCAL_N1 and TCAL_N2')
    parser.add_argument('--bias', metavar='BIAS', type=float, help='DRS4 BIAS voltage (DRS4 internally sets 0.7V usually)')
    parser.add_argument('--rofs', metavar='ROFS', type=float, help='DRS4 read offset voltage (1.05V will capture signals with differential between 0 and 1V well)')

    # parser.add_argument('--oofs', metavar='OOFS', type=float, default=0.8, help='DC offset for DRS4 output into ADC (OOFS)') #?/
    # parser.add_argument('--cmofs', metavar='CMOFS', type=float, default=0.7, help='DC offset into DRS4 (DRS4 wants 0.1 - 1.5V) (CMOFS)')
    # parser.add_argument('--tcal', metavar='TCAL', type=float, default=0.0, help='DC offset for the calibration lines TCAL_N1 and TCAL_N2')
    # parser.add_argument('--bias', metavar='BIAS', type=float, default=0.8, help='DRS4 BIAS voltage (DRS4 internally sets 0.7V usually)')
    # parser.add_argument('--rofs', metavar='ROFS', type=float, default=1.05, help='DRS4 read offset voltage (1.05V will capture signals with differential between 0 and 1V well)')

    # # Hack values for A21
    # parser.add_argument('--oofs', metavar='OOFS', type=float, default=0.0, help='OOFS DAC output voltage')
    # parser.add_argument('--rofs', metavar='ROFS', type=float, default=1.05, help='ROFS DAC output voltage')
    # parser.add_argument('--tcal', metavar='TCAL', type=float, default=1.05, help='Start values for TCAL_N1 and TCAL_N2 DAC output voltage')
    # parser.add_argument('--cmofs', metavar='CMOFS', type=float, default=1.2, help='CMOFS DAC output Voltage')
    # parser.add_argument('--bias', metavar='BIAS', type=float, default=0.7, help='BIAS DAC output Voltage') #usually 0.7
    
    return parser

ifc = None

def connect(parser):

    global ifc

    # Parse the arguments
    args = parser.parse_args()

    # Connect to the board
    ifc = lappdIfc.lappdInterface(args.board, udpsport=args.udpsport)

    # Initialize the board, if requested
    if args.initialize:
        ifc.Initialize()

    # Set the requested threads on the hardware side 
    ifc.brd.pokenow(lappdIfc.NUDPPORTS, args.threads)

    # Give the socket address for use by spawn()
    if args.aim is not None:
        ifc.brd.aimNBIC(port=args.aim)
    
    args.listen = ifc.brd.s.getsockname()[0]

    # Set both adc's if requested
    # XXX? Is this wrong to do at this point?
    if not args.adcmode is None:
        ifc.AdcSetTestMode(0, args.adcmode)
        ifc.AdcSetTestMode(1, args.adcmode)

    # DAC Channel mappings (in A21 crosshacked)
    # (these should be moved to lappdIfc.py)
    DAC_BIAS = 0
    DAC_ROFS = 1
    DAC_OOFS = 2
    DAC_CMOFS = 3
    DAC_TCAL_N1 = 4
    DAC_TCAL_N2 = 5

    derps = [(DAC_BIAS, 'bias'),
             (DAC_ROFS, 'rofs'),
             (DAC_OOFS, 'oofs'),
             (DAC_CMOFS, 'cmofs'),
             (DAC_TCAL_N1, 'tcal'),
             (DAC_TCAL_N2, 'tcal')]

    for dacout, derp in derps:
        eval_derp = eval('args.%s' % derp)
        if not eval_derp is None:
            print("Setting %s to %f..." % (derp, eval_derp))
            for num in (0,1):
                ifc.DacSetVout(num, dacout, eval_derp)
                
    # Set the channels?
    if not args.channels is None:
        args.channels = int(args.channels, base=16)

        ifc.brd.pokenow(0x670, args.channels & 0x00000000FFFFFFFF)
        ifc.brd.pokenow(0x674, (args.channels & 0xFFFFFFFF00000000) >> 32)

    # Set the wait?
    if not args.wait is None:
        ifc.brd.pokenow(lappdIfc.DRSWAITSTART, args.wait)
        print("Setting STOP delay to: %d" % args.wait, file=sys.stderr)

    if not args.external is None:
        ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_EXTTRG_EN_BIT, args.external & 1)

    if not args.pedestal is None:
        ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_PEDSUB_EN_BIT, args.pedestal & 1)
        
    if not args.oscillator is None:
        ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_TCA_ENA_BIT, args.oscillator & 1)

    if not args.zsuppress is None:
        ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_ZERSUP_EN_BIT, args.zsuppress & 1)
        
    # Return a tuble with the interface and the arguments
    return (ifc, args)

#
#
# 
#
def disableTCAL(ifc):

    # Disable OUT4 (TCAL_N1)
    ifc.brd.pokenow(0x1000 | (0x3 << 2), 0x10)
