#!/usr/bin/python3
#import numpy as np
import sys
#import time
import pickle
from os import kill,environ

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
environ['EEVEE_SRC_PATH'] = "./eevee"

import lappdIfc            # Board+firmware *specific* stuff
import eevee

# 1) Load the pedestal
aPedestal = pickle.load(open(sys.argv[2], "rb"))
print("Pedestal file %s loaded." % sys.argv[2])

# 1.5) Connect to the board
board = eevee.board(sys.argv[1])
print("Connection to EEVEE @ %s established." % sys.argv[1])

# 2) Iterate through
#
# Since packets are limited to the maximum ethernet payload 1516 bytes (ish)
# We have 1024 pedestals per channel
# Each register set is a 32bit address and 32bit word
# 
maxSetsPerPacket = 1#28

# Preprocess into a single list first, so we can easily split up
# the transactions
fullPeds = []
for chan in aPedestal.mean:
    for i, ped in enumerate(aPedestal.mean[chan]):

        # Values are stored as signed 16 bit integers.
        # Upload needs to be signed 12 bit integers.
        try:
            fullPeds.append( (chan, i, ((int(ped) + (1 << 15)) >> 4) - (1 >> 11)) )
        except:
            pass

print("Pedestal list flattened.")

# Now assemble transactions
count = 0
for chan,i,ped in fullPeds:

    #if count < maxSetsPerPacket:
    # Multiplication by 4 because 32bits per address
    addr = lappdIfc.ADDR_PEDMEM_OFFSET + (chan << 12) + i*4

    # Add a directive to write this puppy
    board.pokenow(addr, ped)

    #     count += 1 
    # else:
    #     # Execute the transaction
    #     #readback = board.transact()

    print("Sent", chan, i, ped)
        
    # Reset count
    # count = 0

# Done
print("Pedestal written.")
