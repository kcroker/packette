#!/usr/bin/python3
from sys import argv,path
import pickle
from os import environ
#import numpy as np

# Do not ask me why this needs to be included now...
path.append("./eevee")
environ['EEVEE_SRC_PATH'] = "./eevee"

from lappdIfc import ADDR_PEDMEM_OFFSET
import eevee

# 1) Load the pedestal
aPedestal = pickle.load(open(argv[1], "rb"))
print("Pedestal file %s loaded." % argv[1])

# 1.5) Connect to the board
board = eevee.board(argv[2])
print("Connection to EEVEE @ %s established." % argv[2])

# 2) Iterate through
#
# Since packets are limited to the maximum ethernet payload 1516 bytes (ish)
# We have 1024 pedestals per channel
# Each register set is a 32bit address and 32bit word
# 
maxSetsPerPacket = 32

count = 0
tmp = {}
for chan in aPedestal.mean:
    # Write backwards to work around bug in FW108
    derp = enumerate(aPedestal.mean[chan])
    for i, ped in derp:

        # Truncate it
        try:
            ped = (int(ped) & 0xFFFF) >> 4
        except ValueError:
            print("WARNING bad pedestal, channel %d capacitor %d" % (chan, i))
            continue
        
        # Multiplication by 4 because 32bits per address
        addr = ADDR_PEDMEM_OFFSET + (chan << 12) + i*4
                
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

# Dirty HAX for broken firmware pedestal 0 in FW < 109

# for chan in aPedestal.mean:
#     for i, ped in enumerate(aPedestal.mean[chan]):
#         # Truncate it
#         try:
#             ped = (int(ped) & 0xFFFF) >> 4
#         except ValueError:
#             print("WARNING bad pedestal, channel %d capacitor %d" % (chan, i))
#             continue
        
#         # Multiplication by 4 because 32bits per address
#         addr = ADDR_PEDMEM_OFFSET + (chan << 12) + i*4
                
#         # This method guarantees that only one 'register write'
#         # operation is required to set all these registers
#         tmp[addr] = ped if ped >= 0 else ped + 0xFFF + 1
#         count += 1 

#         if count == maxSetsPerPacket:
#             # Execute the transaction (now clears transactions)
#             board.poke(tmp, silent=True)
#             board.transact()
            
#             # Clear it
#             tmp = {}
        
#             # Reset count
#             count = 0

#         break;
    
# Was there any leftover?
if count > 0 and count < maxSetsPerPacket:
    # Execute the transaction
    board.poke(tmp, silent=True)
    board.transact()
    print("Sent residual chunt", chan, i, ped)

# Done
print("Pedestal written.")
