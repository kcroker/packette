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

from collections import namedtuple, OrderedDict

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

# Stuff for packette_stream.py
# (Caching so if you are browsing around between events, they stay in memory)
EVENT_CACHE_LENGTH = 100

# TODO: Implement readahead

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
                # print("mask: %x, channel: %d" % (header['channel_mask'], chan))
                
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

    def parseOffsets(self, fp, fname):
        # This will index event byte boundaries in the underlying stream
        # Lookups can then be done by seeking in the underlying stream
        # Start loading in event data
        prev_event_num = -1
        offsetTable = {}

        index = 0
        
        while True:

            # Grab a header
            #try:
            # To make sure we get binary if stdin is given
            # use the underlying buffer
            header = fp.read(self.header_size)
            index += self.header_size
            #except Exception as e:
            #    print(e)
            #    fp.close()
            #    break

            # If we successfully read something, but it wasn't long enough to be a header,
            # we probably read EOF.
            if len(header) < packette_transport.size:
                break

            # Unpack it and make a dictionary out of it
            header = dict(zip(field_list, packette_transport.unpack(header)))

            # Are we looking at the same board?
            if self.board_id is None:
                self.board_id = header['board_id']
            elif not self.board_id == header['board_id']:
                print(self.board_id)
                print(header['board_id'])
                
                raise Exception("ERROR: Heterogenous board identifiers in multifile event stream.\n " \
                                "\tOutput from different boards should be directed to\n " \
                                "\tdistinct packette instances on disjoint port ranges")

            # This logic is being weird.  Be explicit
            if index == self.header_size or prev_event_num < header['event_num']:
                # Return a tuple with the stream and the byte position within the stream
                self.offsetTable[header['event_num']] = (self.fname_map[fname], index - self.header_size)
                prev_event_num = header['event_num']
                
            # Increment the index by the size of this packet's payload
            index += header['num_samples'] * SAMPLE_WIDTH

            # Seek this amount
            fp.seek(index)
            
        return offsetTable

    def loadEvent(self, event_num):

        # First check cache
        try:
            return self.eventCache[event_num]
        except KeyError as e:
            # Wasn't in there
            pass
        
        # Table lookup (use filenames so that we can pickle the offsetTable)
        fname_index, offset = self.offsetTable[event_num]

        # Now get the fp
        try:
            fp = self.fps[fname_index]
        except IndexError as e:
            try:
                fp = open(fname, "rb")
                self.fps[fname_index] = fp
            except FileNotFoundError as f:
                fprintf(stderr,
                        "packette_stream.py: could not find the backing file %s" % fname)
                
        # Go there
        fp.seek(offset)

        # Load up the event
        while True:

            # Grab a header
            # To make sure we get binary if stdin is given
            # use the underlying buffer
            header = fp.buffer.read(self.header_size)
            
            # If we successfully read something, but it wasn't long enough to be a header,
            # we probably read EOF.
            if len(header) < packette_transport.size:
                # Return what we've got
                break

            # Unpack it and make a dictionary out of it
            header = dict(zip(field_list, packette_transport.unpack(header)))

            # Remember where we are at
            prev_event_num = header['event_num']
            
            # If we've read past the event, return the completed event
            if prev_event_num < header['event_num']:
                break
            
            # Populate the channel data from this transport packet
            chan = event.channels[header['channel']]
            
            # Is this the first data for this channel? 
            if len(chan) == 0:
                # Replace the empty with a properly sized numpy array
                chan.drs4_stop = header['drs4_stop']
                chan.payload = np.zeros(header['total_samples'])
                
            # Read the payload from this packet
            payload = np.frombuffer(fp.buffer.read(header['num_samples']*SAMPLE_WIDTH), dtype=np.uint16)
            #print(payload.shape)
            #print(chan.payload.shape)

            # Write the payload at the relative offset within the numpy array
            # XXX This will glitch if you try to give a rel_offset into a
            #     block that is the block length you are writing
            #     The firmware should never do this to you though...
            chan.payload[header['rel_offset']:header['rel_offset'] + header['num_samples']] = payload

        # Add this event to the cache, removing something if necessary
        self.eventCache[event.event_num] = event

        if len(self.eventCache) > EVENT_CACHE_LENGTH:
            # Get rid of the oldest thing in the cache
            self.eventCache.popitem(last=False)
        
        # Return this event
        return event
    
    def loadAllEvents(self, fp):
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

            # print(header)

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
            #print(payload.shape)
            #print(chan.payload.shape)

            # Write the payload at the relative offset within the numpy array
            # XXX This will glitch if you try to give a rel_offset into a
            #     block that is the block length you are writing
            #     The firmware should never do this to you though...
            chan.payload[header['rel_offset']:header['rel_offset'] + header['num_samples']] = payload

        # Give them back
        return events
    
    # Deinterlace the request
    def __getitem__(self, key):

        if self.osbacked:
            return self.loadEvent(key)
        else:
            numf = len(self.fnames)
            findex = key % numf
            index = math.floor(key / numf)

            # print("Looking up event %d, which should index to stream %d, offset %d" % (key, findex, index))
            # Get the right one
            return self.eventlists[findex][index]

    # Initialize and load the files
    def __init__(self, fnames, osbacked=False):

        # NOTE: fnames is assumed to be sorted in the order you want to deinterlace in!
        # Check for stdin
        self.header_size = packette_transport.size
        self.board_id = None
        self.eventlists = []
        self.offsetTable = {}
        self.eventCache = OrderedDict()
        self.osbacked = osbacked
        self.fnames = fnames
    
        self.fps = {}
        
        if fnames == ['-']:
            if osbacked:
                raise Exception("Cannot seek on stdin.  Take data to a backing file first if you'd like to seek")
            
            self.fps['-'] = sys.stdin
        else:
            self.fps = { f : open(f, 'rb') for f in fnames}

        # Make the fname_map, so we can store integers instead of filenames a bazillion times
        self.fname_map = { f : n for n,f in enumerate(fnames) }
        
        # See if we keep the data on the HD/inside OS buffers
        if osbacked:
            for fname,fp in self.fps.items():
                self.offsetTable.update(self.parseOffsets(fp, fname))
                print("packette_stream.py: built event index for %s" % fname, file=sys.stderr)
        else:
            # Load up a bunch of interleaved events
            for fname,fp in self.fps.items():
                self.eventlists.append(self.loadAllEvents(fp))
                print("packette_python: loaded %s" % fname, file=sys.stderr)

    # So that pickling and unpickling works with file-backed imlementations
    def __getstate__(self):
        state = self.__dict__.copy()
        del state['fps']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

        # Load the fps
        try:
            for fname in fnames:
                self.fps = {f : open(f, 'rb') for f in fnames}
        except FileNotFoundError as e:
            print("packette_stream.py: could not find one of the given files", file=sys.stderr)
            
    # Return the total number of events described by this run
    def __len__(self):
        if self.osbacked:
            return len(self.offsetTable)
        else:
            return sum([len(l) for l in self.eventlists])

    # An iterator to support list-like interaction
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
events = packetteRun(sys.argv[1:], osbacked='True')
print("Loaded %d events" % len(events))

import pickle
pickle.dump(events, open("pickledPacketteRun.dat", "wb"))

print(events.offsetTable)

# Now lets try some accesses
for event in events:
    for chan,data in event.channels.items():
        for datum in data:
            print("event %d, channel %d, payload:\n" % (event.event_num, chan, datum))
