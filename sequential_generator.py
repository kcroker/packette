#!/usr/bin/python3

import os
import sys
import socket
import select
import random
import struct
import time

# Transport packet format
packette_transport_format = '6s H Q   I I 8s   I I I I'

# Make an encoder
packette_transport = struct.Struct(packette_transport_format)

# I got myself a shorty
from collections import namedtuple

field_list = ['board_id',
              'rel_offset',
              'seqnum',
              'event_num',
              'trigger_low',
              'channel_mask',
              'num_samples',
              'channel',
              'total_samples',
              'drs4_stop']

# Got myself a 40
packette_tuple = namedtuple('packette_tuple', field_list)

# Make an empty dict
a_packette = { key : None for key in field_list }

# Set it up
a_packette['board_id'] = bytearray.fromhex('001337CA7500')
a_packette['rel_offset'] = 0
a_packette['seqnum'] = 0
a_packette['event_num'] = 7
a_packette['trigger_low'] = 12345
a_packette['channel_mask'] = bytearray.fromhex('00 00 00 00 00 00 00 01')
a_packette['num_samples'] = 1024
a_packette['channel'] = 4
a_packette['total_samples'] = 1024
a_packette['drs4_stop'] = 126

payload = bytearray(2048)

# Go get lifted
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((sys.argv[1], int(sys.argv[2])))

# Now start blasting
while True:

    # Sigh: Convert (unordered dictionary) -> namedtuple -> C structure
    header = packette_transport.pack(*packette_tuple(**a_packette))

    # How's that for convoluted slicing syntax?
    # Stick the header at the front of the payload
    # (since payload is the mutable type)
    payload[0:0] = header

    # Bye bye
    s.send(payload)
    
    # Increment
    a_packette['seqnum'] += 1
    
    # Sleep
    time.sleep(0.1)
