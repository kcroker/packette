#!/usr/bin/python3

import argparse
import multiprocessing
from os import kill,environ
from signal import SIGINT
import sys
import numpy as np
import re

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

    parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, help='Aim the board at this port on this machine.')
    parser.add_argument('-c', '--channels', metavar='CHANNELS', help="Explicitly force a hex channel mask. (Persistent)")
    parser.add_argument('-w', '--wait', metavar='WAIT', type=int, help="Adjust delay between receipt of soft/hard trigger and DRS4 sampling stop. (Persistant)")
    parser.add_argument('-u', '--udpsport', metavar='UDPSPORT', type=int, help="Set the originating port for outgoing control signals explicitly")
    
    parser.add_argument('-N', metavar='NUM_SAMPLES', type=int, default=0, help='Issue N soft triggers of the board')
    parser.add_argument('-r', '--rate', metavar='RATE', type=float, default=100, help='The rate (in Hz) of software triggers')
    parser.add_argument('-I', '--initialize', action="store_true", help="Initialize the board")
    parser.add_argument('-t', '--threads', metavar="NUM_THREADS", type=int, help="Number of distinct ports to receive data.  Ports increment from the aimed port.")

    parser.add_argument('--adctestpattern', help='ADC custom mode test pattern')
    parser.add_argument('-e', '--external', type=int, help='Adjust extriggering (odd is on)')
    parser.add_argument('-p', '--pedestal', type=int, help='Adjust hardware pedestal subtraction (odd is on)')
    parser.add_argument('-z', '--zsuppress', type=int, help='Adjust firmware zero channel suppression (odd is on)')
    parser.add_argument('-O', '--oscillator', type=int, help='Adjust internal 100Mhz oscillator on all TCAL lines (odd is on)')
    parser.add_argument('--adcmode', type=str, help='Put the ADC into alternate modes for debugging')

    parser.add_argument('--andtrigger', help="Specific necessary channels over threshold for a trigger")
    parser.add_argument('--ortrigger', help="Any of these channels over threshold will cause a trigger")
    
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

    # Sanity checks
    if args.rate <= 0:
        print("Given rate", args.rate, "is non-sensical.")
        exit(1)

    # Connect to the board
    ifc = lappdIfc.lappdInterface(args.board, udpsport=args.udpsport)

    # Initialize the board, if requested
    if args.initialize:
        ifc.Initialize()

    # Set the requested threads on the hardware side
    if args.threads is not None:
        ifc.brd.pokenow(lappdIfc.NUDPPORTS, args.threads)

    # Give the socket address for use by spawn()
    if args.aim is not None:
        ifc.brd.aimNBIC(port=args.aim)
    
    args.listen = ifc.brd.s.getsockname()[0]

    # Set both adc's if requested
    # XXX? Is this wrong to do at this point?
    if not args.adcmode is None:
        if not args.adctestpattern is None and args.adcmode == 'custom':
            args.adctestpattern = int(args.adctestpattern, 0)
            
            ifc.AdcSetTestPat(0, args.adctestpattern)
            ifc.AdcSetTestPat(1, args.adctestpattern)
            
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
        try:
            args.channels = int(args.channels, base=16)
        except ValueError as e:
            # Allow the same channel specifications as the browser
            args.channels = chans2bitmask(parse_speclist(args.channels))

        # Write it out all at once
        writemask(lappdIfc.ADCCHANMASK_0, args.channels)

    # Set the and mask?
    if not args.andtrigger is None:
        try:
            args.andtrigger = int(args.andtrigger, base=16)
        except ValueError as e:
            args.andtrigger = chans2bitmask(parse_speclist(args.andtrigger))

        # Write it out
        writemask(lappdIfc.ZERSUPMASKAND_0, args.andtrigger)

    # Set the or mask?
    if not args.ortrigger is None:
        try:
            args.ortrigger = int(args.ortrigger, base=16)
        except ValueError as e:
            args.ortrigger = chans2bitmask(parse_speclist(args.ortrigger))

        # Write it out
        writemask(lappdIfc.ZERSUPMASKOR_0, args.ortrigger)

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
# Strip mappings to channels.
# Strips are counted from the SFP cage regarded as the upper left,
# from the back of the tile.  Lowest strip is left-most. Strips are 1 indexed,
# because Jesus hates your freedoms.
#

strips = {  28  : (0,62),
            27  : (1,61),
            26  : (2,60),
            25  : (3,59),
            24  : (4,58),
            23  : (5,57),
            22  : (6,56),
           
            21  : (8,54),
            20  : (9,53),
            19  : (10, 52),
            18  : (11, 51),
            17  : (12, 50),
            16  : (13, 49),
            15  : (14, 48),
           
            14  : (16, 46),
            13  : (17, 45),
            12  : (18, 44),
            11  : (19, 43),
            10  : (20, 42),
            9  : (21, 41),
            8  : (22, 40),
        
            7  : (24, 38),
            6  : (25, 37),
            5  : (26, 36),
            4  : (27, 35),
            3  : (28, 34),
            2  : (29, 33),
            1  : (30, 32)}

inverse_strips = { v : k for k,v in strips.items() }

exploded_inverse_strips = {}
for key,val in strips.items():
    l,r = val
    exploded_inverse_strips[l] = key
    exploded_inverse_strips[r] = key

calibrations = { 1 : 7,
                 2 : 15,
                 3 : 23,
                 4 : 31,
                 5 : 39,
                 6 : 47,
                 7 : 55,
                 8 : 63 }

inverse_calibrations = { v : k for k,v in calibrations.items() }                 

def parse_speclist(speclist):

    # Speclist looks like
    # [!]n1, [!]n2-n3, [!]s(x), [!]s(x)-s(y)...

    # Make a regex for matching strip
    p = re.compile(r's\((.*)\)')
    
    # Received
    print("Received: ", speclist)
    
    # Get the individual specs
    specs = [x.strip() for x in speclist.split(',')]

    exclusions = []
    inclusions = []
    
    for spec in specs:

        # See if they are negated
        negated = False
        if spec[0] == '!':
            negated = True
            spec = spec[1:]
            
        try:
            # First see if its a tile strip
            m = p.match(spec)
            if not m is None:

                # Extract the strip number as a string
                m = m.group(1)

                print("Matched", m)
                
                # Get strip tuples of channels
                tuples = [strips[s] for s in parse_speclist(m)]

                # Inefficient comparison ::puke::
                for tup in tuples:
                    if negated:
                        exclusions += tup
                    else:
                        inclusions += tup 
            else:        
                # Extract the bounds
                bounds = [int(x) for x in spec.split('-')]

                # Double up if necessary
                if len(bounds) < 2:
                    bounds.append(bounds[0])
                
                # Flip the if reversed
                if bounds[0] > bounds[1]:
                    tmp = bounds[1]
                    bounds[1] = bounds[0]
                    bounds[0] = tmp

                # Add it to the appropriate list
                # Interpret bounds as inclusive
                if negated:
                    exclusions += range(bounds[0], bounds[1]+1)
                else:
                    inclusions += range(bounds[0], bounds[1]+1)

        except ValueError as e:
            print("Did not understand %s, skipping..." % spec)


    print("Include: ", inclusions)
    print("Exclude: ", exclusions)
    
    # Filter out the exclusions from the inclusions
    return [x for x in inclusions if x not in exclusions]

#
# Do a block write of EEVEE register space, using
# fast register trasnactions
#
# Eventually, this should be replaced with some sort bulk write
# from a base pointer in C, with a different type of EEVEE transaction
#
def blockwrite(board, baseaddr, data, chunksize=32):

    # Start at the beginning
    offset = 0
    
    while offset < len(data):

        # Reset it
        act = {}
        count = 0
        
        # Build up a chunk
        while count < chunksize:
            act[baseaddr + offset*4] = data[offset]
            offset += 1
            count += 1

            # Check for end of data
            if offset == len(data):
                break
    
        # Write out the chunk, or any remainder
        board.poke(act, silent=True)
        board.transact()

#
# NOTE: length is not byte length, its number of 32-bit addresses to 
#       qwerty
#
def blockread(board, baseaddr, length, chunksize=32, cast=np.int16):
    # Start at the beginning
    offset = 0

    results = {}
    
    while offset < length:

        # Reset it
        act = {}
        count = 0
        
        # Build up a chunk
        while count < chunksize:
            act[baseaddr + offset*4] = 0x0
            offset += 1
            count += 1

            # Check for end of data
            if offset == length:
                break
    
        # Read out the chunk, or any remainder
        board.peek(act)

        # Zero index because there was a single transaction
        # .data because this attribute contains the reconstructed register dictionary
        regdict = board.transact()[0].data
        results = {**results, **regdict}

    # Now assemble the resulting dictionary back into a contiguous numpy type
    datablock = np.zeros((length), dtype=cast)

    offset = 0
    while offset < length:
        datablock[offset] = results[baseaddr + offset*4]
        offset += 1

    # Return the datablock
    return datablock
    
#
# Convenience coverter from signed millivolts to natural ADC units
# (use it with vectorized numpy types)
#
def mVtoADC(mV):
    return int((mV / 1000.) * 2048)
    

#
# Convenience converter from natural ADC units to millivolts
# (use it with vectorized numpy types)
#
def ADCtomV(adc):
    return adc * 1000. / 2048

def chans2bitmask(chans):

    mask = 0x0

    for chan in chans:
        mask |= 1 << chan

    return mask

#
# Write a 64 bit mask, in little endian.
# Do them both at once, so there's a greater chance of success under high rate.
#
def writemask(baseaddr, mask):
    ifc.brd.poke({ baseaddr : mask & 0x00000000FFFFFFFF,
                   baseaddr+4 : (mask & 0xFFFFFFFF00000000) >> 32 }, readback=False)
    ifc.brd.transact()
    
