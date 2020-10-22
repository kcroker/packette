#!/usr/bin/python3

#
# packette_python.py
# Copyright(c) 2020 Kevin Croker
#  for the Nishimura Instrumentation Fronteir Taskforce
#
# GNU GPL v3
#
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
# Provides a lightweight Python 3 interface to packette protocol transport frames.
#
# packetteRun objects allow you to browse events interlaced across multiple files
# with a list access [].
#
# packetteEvent objects allow you to browse individual channels via
# a dictionary access.
#
# packetteChannel objects allow you to browse all individual array positions
# via a list access [].  Backing data is sparse, with unbacked positions
# returning the "no data" bits high.
#

import struct
import math
import numpy as np
import sys
import os

from collections import namedtuple

# Transport packet format incantation
packette_transport_format = '6s H Q   I I Q   H H H H'

# Make an encoder
packette_transport = struct.Struct(packette_transport_format)

# I got myself a shorty
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

# Sample width should be defined universally somwhere
SAMPLE_WIDTH = 2
NO_DATA = -1

class packetteRun(object):

    # The simple event class, contains a list of packette_channel objects
    # These are backed by numpy arrays, but support indexing beyond the present data
    class packetteEvent(object):

        def __init__(self, header):
            self.channels = {}

            self.event_num = header['event_num']
            self.trigger_low = header['trigger_low']
            
            # For every channel thats on in the mask, make a dictionary entry to it
            chan = 0
            while chan < 64:
                print("mask: %x, channel: %d" % (header['channel_mask'], chan))
                
                if header['channel_mask'] & 0x1:
                    self.channels[chan] = self.packetteChannel(0, np.empty([0], dtype=np.uint16))

                # Advance to the next place in the mask
                header['channel_mask'] >>= 1
                chan += 1
                
        # This acts like an array access, except
        # it returns NO_DATA for values that are not
        # defined 
        class packetteChannel(object):

            # data is a numpy array
            def __init__(self, drs4_stop, payload):
                self.drs4_stop = drs4_stop
                self.payload = payload

            # Length
            def __len__(self):
                return len(self.payload)

            # Return the data if its there, otherwise return NO_DATA
            def __getitem__(self, key):

                if not isinstance(key, int):
                    raise IndexError("key must be an integer")

                if key < 0 or key > 1024:
                    raise IndexError("key lies outside of DRS4 switched cap array")

                # Relative view
                # Get the offset into the data we have
                i = (self.drs4_stop + key) & 1023

                # Return the data if its there
                if i < len(self):
                    return self.payload[i]
                else:
                    return NO_DATA

            def __iter__(self):
                return self.channelIterator(self)

            class channelIterator(object):
                def __init__(self, channel):
                    self.channel = channel
                    self.i = 0

                def __next__(self):
                    try:
                        datum = self.channel[self.i]
                    except IndexError as e:
                        raise StopIteration
            
                    self.i += 1
                    return datum
        
    def loadEvents(self, fp):
        # Start loading in event data
        prev_event_num = -1
        event = None
        events = []
        
        while True:

            # Grab a header
            try:
                # To make sure we get binary if stdin is given
                # use the underlying buffer
                header = fp.buffer.read(self.header_size)
            except Exception as e:
                print(e)
                fp.close()
                break

            # If we successfully read something, but it wasn't long enough to be a header,
            # we probably read EOF.
            if len(header) < packette_transport.size:
                break

            # Unpack it and make a dictionary out of it
            header = dict(zip(field_list, packette_transport.unpack(header)))

            print(header)

            # Are we looking at the same board?
            if self.board_id is None:
                self.board_id = header['board_id']
            elif not self.board_id == header['board_id']:
                raise Exception("ERROR: Heterogenous board identifiers in multifile event stream.\n " \
                                "\tOutput from different boards should be directed to\n " \
                                "\tdistinct packette instances on disjoint port ranges")

            # This logic is being weird.  Be explicit
            if event is None or prev_event_num < header['event_num']:
                # Make one and add it
                event = self.packetteEvent(header)
                prev_event_num = header['event_num']
                events.append(event)                
                
            # Populate the channel data from this transport packet
            chan = event.channels[header['channel']]
            
            # Is this the first data for this channel? 
            if len(chan) == 0:
                # Replace the empty with a properly sized numpy array
                chan.drs4_stop = header['drs4_stop']
                chan.payload = np.zeros(header['total_samples'])
                
            # Read the payload from this packet
            payload = np.frombuffer(fp.buffer.read(header['num_samples']*SAMPLE_WIDTH), dtype=np.uint16)
            print(payload.shape)
            print(chan.payload.shape)

            # Write the payload at the relative offset within the numpy array
            chan.payload[header['rel_offset']:header['rel_offset'] + header['num_samples']] = payload

        # Give them back
        return events
    
    # Deinterlace the request
    def __getitem__(self, key):
        numf = len(self.fnames)
        findex = key % numf
        index = math.floor(key / numf)

        print("Looking up event %d, which should index to stream %d, offset %d" % (key, findex, index))
        # Get the right one
        return self.eventlists[findex][index]

    # Initialize and load the files
    def __init__(self, fnames):

        # NOTE: fnames is assumed to be sorted in the order you want to deinterlace in!
        # Check for stdin
        self.header_size = packette_transport.size
        self.board_id = None
        self.eventlists = []
        
        self.fnames = fnames
        
        if fnames == ['-']:
            self.fps = [sys.stdin]
        else:
            self.fps = [open(f, 'rb') for f in fnames]

        # Load up a bunch of interleaved events
        for fname,fp in zip(self.fnames, self.fps):
            self.eventlists.append(self.loadEvents(fp))
            print("packette_python: loaded %s" % fname, file=sys.stderr)

    def __iter__(self):
        return self.runIterator(self)

    class runIterator(object):
        def __init__(self, run):
            self.run = run
            self.i = 0

        def __next__(self):
            try:
                event = self.run[self.i]
            except IndexError as e:
                raise StopIteration
            
            self.i += 1
            return event
        
# Testing stub
events = packetteRun(['-'])

for event in events:
    for chan, data in event.channels.items():
        print("Event %d\nChannel: %d\nData: " % (event.event_num, chan))
        print("drs4_stop: %d" % data.drs4_stop)
        for datum in data:
            print(datum)
        
        
