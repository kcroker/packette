#!/usr/bin/python3

import os
import sys
import socket
import select
import random
import struct
import time
import numpy as np

# Transport packet format
packette_transport_format = '6s H Q   I I Q   H H H H'

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
a_packette['seqnum'] = 0

a_packette['event_num'] = 7
a_packette['trigger_low'] = 12345
a_packette['channel_mask'] = 0x00000000000000011

a_packette['num_samples'] = 512
a_packette['channel'] = 4
a_packette['total_samples'] = 1022
a_packette['drs4_stop'] = 1000

payload = np.array(range(a_packette['total_samples']), dtype=np.uint16)

# Make the valid data
payload <<= 4

# Go get lifted
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((sys.argv[1], int(sys.argv[2])))

# Alloc a buffer
buf = bytearray()

# Now start blasting
while True:

    
    # Sigh: Convert (unordered dictionary) -> namedtuple -> C structure
    a_packette['rel_offset'] = 0
    a_packette['num_samples'] = 512
    header = packette_transport.pack(*packette_tuple(**a_packette))
    buf = header + payload[a_packette['rel_offset']:a_packette['rel_offset'] + a_packette['num_samples']].tobytes()
    s.send(buf)
    
    # Increment
    a_packette['seqnum'] += 1
    a_packette['rel_offset'] = a_packette['num_samples']
    a_packette['num_samples'] = a_packette['total_samples'] - a_packette['num_samples']
    header = packette_transport.pack(*packette_tuple(**a_packette))
    buf = header + payload[a_packette['rel_offset']:a_packette['rel_offset'] + a_packette['num_samples']].tobytes()
    s.send(buf)
    
    # Increment
    a_packette['seqnum'] += 1
    a_packette['event_num'] += 1
    
    # Sleep
    time.sleep(0.01)
