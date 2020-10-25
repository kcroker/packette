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
NOT_DATA = 0x4

# Stuff for packette_stream.py
# (Caching so if you are browsing around between events, they stay in memory)
EVENT_CACHE_LENGTH = 100

# TODO: Implement readahead

class packetteRun(object):

    # The simple event class, contains a list of packette_channel objects
    # These are backed by numpy arrays, but support indexing beyond the present data
    class packetteEvent(object):

        def __init__(self, header, run):
            self.channels = {}
            self.run = run
            self.event_num = header['event_num']
            self.trigger_low = header['trigger_low']
            
            # For every channel thats on in the mask, make a dictionary entry to it
            chan = 0
            while chan < 64:
                # print("mask: %x, channel: %d" % (header['channel_mask'], chan))
                
                if header['channel_mask'] & 0x1:
                    self.channels[chan] = self.packetteChannel(0, np.empty([0], dtype=np.uint16), self.run)

                # Advance to the next place in the mask
                header['channel_mask'] >>= 1
                chan += 1
                
        # This acts like an array access, except
        # it returns NO_DATA for values that are not
        # defined 
        class packetteChannel(object):

            # data is a numpy array
            def __init__(self, drs4_stop, payload, run):
                self.drs4_stop = drs4_stop
                self.payload = payload
                self.run = run
                self.resetMask()

            # Masking allows you to ignore certain troublesome regions
            # Masks are always in SCA view.
            def mask(self, low, high):
                span = high - low
                if span < 0:
                    raise ValueError("Requested mask is backwards")

                # Set the mask
                self.sca_mask[low:high] = np.repeat(0, span)

            def unmask(self, low, high):
                span = high - low
                if span < 0:
                    raise ValueError("Requested unmask is backwards")

                # Set the mask
                self.sca_mask[low:high] = np.repeat(1, span)

            def resetMask(self):
                self.sca_mask = np.repeat(1, len(self))
                
            # Length
            def __len__(self):
                return len(self.payload)

            # Return the data if its there, otherwise return NO_DATA
            def __getitem__(self, key):

                if not isinstance(key, int):
                    raise IndexError("key must be an integer")

                if key < 0 or key > 1024:
                    raise IndexError("key lies outside of DRS4 switched cap array")

                # The data is described relative to the drs4_offset, which is absolute in position
                if not self.run.SCAView:
                    # key = 0 corresponds to the stop sample, so this is *time ordered*
                    i = (self.drs4_stop + key) & 1023
                else:
                    # key = 0 corresponds to the absolute zero, so this is *capacitor ordered*
                    i = key

                # Return the data if its there
                if i < len(self) and self.sca_mask[i]:
                    return self.payload[i]
                else:
                    return NOT_DATA

            # Dump the channel stop, mask, and contents
            def __str__(self):
                return "drs4_stop: %d\n" \
                    "sca_mask:\n%s\n" \
                    "payload:\n%s\n" % (self.drs4_stop, self.sca_mask, self.payload) 
                
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

    def parseOffsets(self, fp, fhandle, index):
        # This will index event byte boundaries in the underlying stream
        # Lookups can then be done by seeking in the underlying stream
        # Start loading in event data
        prev_event_num = -1
        offsetTable = {}

        # Yikes, forgot to do the initial seek
        fp.seek(index)
        
        while True:

            header = fp.read(self.header_size)
            index += self.header_size

            # If we successfully read something, but it wasn't long enough to be a header,
            # we probably read EOF.
            if len(header) < packette_transport.size:
                index -= self.header_size
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
                self.offsetTable[header['event_num']] = (fhandle, index - self.header_size)
                prev_event_num = header['event_num']
                
            # Increment the index by the size of this packet's payload
            index += header['num_samples'] * SAMPLE_WIDTH

            # Seek this amount
            fp.seek(index)

        # Set the most recently successful read
        self.fp_indexed[fhandle] = index
        
        return offsetTable

    # Time ordered views return capacitor DRS4_STOP when requesting index 0
    # Capacitor ordered views return capacitor 0 when requesting index 0
    def setSCAView(self, flag):
        self.SCAView = flag
                
    def loadEvent(self, event_num):

        # First check cache
        try:
            return self.eventCache[event_num]
        except KeyError as e:
            # Wasn't in there
            pass
        
        # Table lookup
        fhandle, offset = self.offsetTable[event_num]

        # Now get the fp
        try:
            fp = self.fps[fhandle]
        except IndexError as e:
            fprintf(stderr,
                    "packette_stream.py: backing file %s was not loaded?" % self.fnames[fhandle])
                
        # Go there
        fp.seek(offset)

        event = None
        
        # Load up the event
        while True:

            # Grab a header
            # To make sure we get binary if stdin is given
            # use the underlying buffer
            header = fp.read(self.header_size)
            
            # If we successfully read something, but it wasn't long enough to be a header,
            # we probably read EOF.
            if len(header) < packette_transport.size:
                # Return what we've got
                break

            # Unpack it and make a dictionary out of it
            header = dict(zip(field_list, packette_transport.unpack(header)))

            if event is None:
                # Remember where we are at
                prev_event_num = header['event_num']
                event = self.packetteEvent(header, self)
            
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

                # Add a 5 sample symmetric mask around the stop sample
                chan.mask(header['drs4_stop'] - 5, header['drs4_stop'] + 5)
                
            # Now, since the underlying stream may be growing, we might have gotten a header
            # but we don't have enough underlying data to finish out the event here
            capacitors = fp.read(header['num_samples']*SAMPLE_WIDTH)
            
            # Verify that we *got* this amount
            if not len(capacitors) == header['num_samples']*SAMPLE_WIDTH:

                # We didn't get this payload yet, that's fine.
                # It'll work on the next read.
                break
                
            # Read the payload from this packet
            payload = np.frombuffer(capacitors, dtype=np.uint16)

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
    
    def __getitem__(self, key):
        return self.loadEvent(key)
        
    # Initialize and load the files
    def __init__(self, fnames, SCAView=False):

        # NOTE: fnames is assumed to be sorted in the order you want to deinterlace in!
        # Check for stdin
        self.header_size = packette_transport.size
        self.board_id = None
        self.eventlists = []
        self.offsetTable = {}
        self.eventCache = OrderedDict()

        self.SCAView = SCAView
        
        # We usually expect lists.  If its a one off, wrap it in a list
        if not isinstance(fnames, list):
            fnames = [fnames]
        
        self.fnames = fnames
        self.fps = {}
        self.fp_indexed = {}
        
        if fnames == ['-']:
            raise Exception("Cannot seek on stdin.  Start taking data to a backing file, and specify that file to work in real-time")
            
        # This stores integer handles to file pointers that back the event data
        self.fps = { n : open(f, 'rb') for n,f in enumerate(fnames)}

        # This stores the most recent position where a header read failed
        # (used to update the index on the fly)
        self.fp_indexed = { n : 0 for n in range(len(fnames))}
        
        # See if we keep the data on the HD/inside OS buffers
        for fhandle,fp in self.fps.items():

            # Didn't seem to work...
            # Make sure we get the most recent jazz
            # os.fsync(fp.fileno())

            # Send it the 0 index, since this is the first time we are building the index
            self.offsetTable.update(self.parseOffsets(fp, fhandle, 0))
            print("packette_stream.py: built event index for %s" % fnames[fhandle], file=sys.stderr)

    # For underlying streams that are growing, we can update the index
    def updateIndex(self):
        # Start parsing offsets at the last successful spot
        for fhandle,fp in self.fps.items():
            print("packette_stream.py: syncing OS buffers for %s..." % self.fnames[fhandle],
                  file=sys.stderr)

            # Didn't seem to work...
            # Make sure we get the most recent jazz
            os.fsync(fp.fileno())

            # Force a seek to the end
            fp.seek(0,2)
            
            print("packette_stream.py: resuming indexing of %s at byte position %d..." % (self.fnames[fhandle], self.fp_indexed[fhandle]),
                  file=sys.stderr)

            # This will seek from where we previously left off
            self.parseOffsets(fp, fhandle, self.fp_indexed[fhandle])
    
    # So that pickling and unpickling works with file-backed imlementations
    def __getstate__(self):
        state = self.__dict__.copy()
        del state['fps']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

        print("packette_stream.py: pickled run contains %d events backed by:" % len(self), file=sys.stderr)
        # Load the fps
        try:
            for fname in self.fnames:
                self.fps = {n : open(f, 'rb') for n,f in enumerate(self.fnames)}
                print("\t%s" % fname,file=sys.stderr)
                
        except FileNotFoundError as e:
            print("packette_stream.py: could not find one of the given files", file=sys.stderr)

        # Update the index
        self.updateIndex()

        # Report
        print("packette_stream.py: after update, run contains %d events" % len(self), file=sys.stderr)
        
    # Return the total number of events described by this run
    def __len__(self):
        return len(self.offsetTable)

    # An iterator to support list-like interaction
    def __iter__(self):
        return self.runIterator(self)

    class runIterator(object):
        def __init__(self, run):
            self.run = run
            self.i = 0
            self.offsetIterator = iter(run.offsetTable.items())

        def __next__(self):

            # We'll need an enumeration of the offsetTable to go
            # through events in order
            try:
                event_num, whatever = self.offsetIterator.__next__()
                event = self.run[event_num]
            except IndexError as e:
                raise StopIteration
            
            self.i += 1
            return event

# Testing stub
def test():
    events = packetteRun(sys.argv[1:])
    print("Loaded %d events" % len(events))

    import pickle
    pickle.dump(events, open("pickledPacketteRun.dat", "wb"))

    # Now lets try some accesses
    # Works
    for event in events:
        for chan,data in event.channels.items():
            print("event %d, channel %d\n" % (event.event_num, chan))
            for n, datum in enumerate(data):
                if (n & 15) == 15:
                    print("")
                print("%4d " % datum, end='')
    print('')
    
    # Switch to capacitor view
    events.setSCAView(True)

    # Look at it using native dumps
    for event in events:
        for chan,data in event.channels.items():
            print("event %d, channel %d\n" % (event.event_num, chan))
            print(data)
            
    print('')
    
    # import time
    # time.sleep(5)

    # # Test an update
    # events.updateIndex()

    # # Test the pickle
    # events = pickle.load(open("pickledPacketteRun.dat", "rb"))
    # print("Loaded %d events" % len(events))

    
# Invoke it
test()    

