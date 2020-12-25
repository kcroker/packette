#!/usr/bin/python3
import sys
import pickle
from os import kill,environ
import numpy as np

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
maxSetsPerPacket = 128

count = 0
tmp = {}
for chan in aPedestal.mean:
    for i, ped in enumerate(aPedestal.mean[chan]):

        # Multiplication by 4 because 32bits per address
        addr = lappdIfc.ADDR_PEDMEM_OFFSET + (chan << 12) + i*4

        # Truncate it
        ped = (np.int64(ped) & 0xFFFF) >> 4
        
        # This method guarantees that only one 'register write'
        # operation is required to set all these registers
        tmp[addr] = ped if ped >= 0 else ped + 0xFFF + 1
        count += 1 

        if count == maxSetsPerPacket:
            # Execute the transaction (now clears transactions)
            board.poke(tmp, silent=True)
            board.transact()

            # Clear it
            tmp = {}
        
            # Reset count
            count = 0

# Was there any leftover?
if count > 0 and count < maxSetsPerPacket:
    # Execute the transaction
    board.poke(tmp, silent=True)
    board.transact()
    
    print("Sent residual chunt", chan, i, ped)

# Done
print("Pedestal written.")
