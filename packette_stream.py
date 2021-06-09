#!/usr/bin/python3

#
# packette_python.py
# Copyright(c) 2020 Kevin Croker
#  for the Nishimura Instrumentation Frontier Taskforce
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
import time
import socket
import select
import bisect

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
MASKED_DATA = 0x8

# Stuff for packette_stream.py
# (Caching so if you are browsing around between events, they stay in memory)
EVENT_CACHE_LENGTH = 100

# Stuff for not waste memory gooder
# (return views into this thing)
empty_payload = np.full([1024], NOT_DATA, dtype=np.int16)

# Make it the pretty
np.set_printoptions(formatter = {'int' : lambda x : '%5d' % x})

# TODO: Implement readahead
        
# This acts like an array access, except
# it returns NO_DATA for values that are not
# defined 
class packetteChannel(object):

    # data is a numpy array
    def __init__(self, drs4_stop, payload, run):
        self.drs4_stop = drs4_stop
        self.payload = payload
        self.run = run
        self.length = len(payload)
        self.masks = []

        # Now, make a full array view for fast access
        self.cachedView = np.full([1024], NOT_DATA, dtype=np.int16) 

        # Invalidate the cache, so that we have to build it
        self.cacheValid = False

    # Length
    def __len__(self):
        return self.length

    # Return the data if its there, otherwise return NO_DATA
    def __getitem__(self, i):

        # If cache is valid, return directly
        if not self.cacheValid:
            self.buildCache()

        return self.cachedView[i]

    #
    # The strategy to do fast computations is that iterators and arithmetic operations
    # always return the cached view.  So you're working directly with numpy primatives
    #
    def __iter__(self):
        # Return the iterator of the cachedView
        return iter(self.cachedView)

    def __inv__(self, x):
        return ~self.cachedView

    def __and__(self, x):
        return self.cachedView & x

    def __or__(self, x):
        return self.cachedView | x

    def __mul__(self, x):
        # Multiply the cachedViews.  Allows to vectorize the channels
        if isinstance(x, packetteChannel):
            return self.cachedView * x.cachedView
        else:
            return self.cachedView * x

    # Dump the channel stop, mask, and contents
    def __str__(self):

        divider = "---------------------------------------\n"
        msg = 'rel_offset: %d\n' % self.rel_offset
        msg += "drs4_stop: %d\n" \
               "length: %d\n" \
               "cacheValid: %s\n"  % (self.drs4_stop, len(self), self.cacheValid)
        msg += divider
        msg += "masks:\n"
        if len(self.masks) > 0:
            for mask in self.masks:
                msg += str(mask) + "\n"
        else:
            msg += "None"

        msg += "\n" + divider
        msg += "payload (raw):\n"
        msg += dumpPayload(self.payload)
        msg += "\n" + divider
        msg += "cachedView:\n"
        msg += dumpCachedView(self.cachedView)

        return msg

    def mask(self, low, high):

        # Nop
        if low == high:
            return

        # Check for sanity
        if low > high:
            raise ValueError("Low end of mask needs to exceed the high end of the mask")
        elif high - low > 1024:
            raise ValueError("Specified mask exceeds length of capacitor array")
        elif low < 0 and high < 0:
            raise ValueError("Don't be obnoxious")

        # Now check for negative masks
        if low < 0:
            self.masks.append((1024 + low, 1024))
            self.masks.append((0, high))
        elif high > 1023:
            self.masks.append((low, 1024))
            self.masks.append((0, high-1024))
        else:
            self.masks.append((low, high))

    def clearMasks(self):
        self.masks = []
        self.buildCache()

    def masksToSCA(self):
        newmasks = []

        for low, high in self.masks:
            low += self.drs4_stop
            high += self.drs4_stop

            if low > 1024 and high > 1024:
                # We completely overflowed, wrap around
                low = 1024 - low
                high = 1024 - high
                newmasks.append((low,high))
            elif high > 1024:
                # We partially overflowed, so we need two masks now
                newmasks.append((low, 1024))
                newmasks.append((0, high - 1024))
            else:
                newmasks.append((low, high))

        # Replace the old masks
        self.masks = newmasks

    def masksToTime(self):
        newmasks = []

        for low, high in self.masks:
            low -= self.drs4_stop
            high -= self.drs4_stop

            if low < 0 and high < 0:
                # We completely underflowed, wrap around
                prevhigh = high
                high = low + 1024
                low = prevhigh + 1024
                newmasks.append((low, high))
            elif low < 0:
                # We partially underflowed, so we need two masks now
                newmasks.append((1024+low, 1023))
                newmasks.append((0, high))
            else:
                newmasks.append((low, high))

        self.masks = newmasks

    def buildCache(self):

        # Invalidate the cache
        self.cacheValid = False

        # Cleanse the the cachedView
        self.cachedView.fill(NOT_DATA)

        # Write the payload into the appropriate location into the cache
        if self.run.SCAView:
            # Capacitor ordering

            # First write up to the end
            if self.length > 1024-self.drs4_stop:
                upto = 1024-self.drs4_stop
                self.cachedView[self.drs4_stop:] = self.payload[:upto]
                self.cachedView[0:self.length - upto] = self.payload[upto:]
            else:
                # No wraparound required
                self.cachedView[self.drs4_stop:self.drs4_stop + self.length] = self.payload
        else:
            # Time ordering
            self.cachedView[0:self.length] = self.payload

        # Now apply masking
        for low,high in self.masks:
            self.cachedView[low:high] = MASKED_DATA

        # Now always pull from cache
        self.cacheValid = True

# The simple container class, contains a list of packette_channel objects
# These are backed by numpy arrays, but support indexing beyond the present data
class packetteEvent(object):

    def __init__(self, header, run):
        self.channels = {}
        self.run = run
        self.event_num = header['event_num']
        self.trigger_low = header['trigger_low']

        # For every channel thats on in the mask, make a dictionary entry to it
        chan = 0
        chanmask = header['channel_mask'] 
        while chan < 64:
            # print("mask: %x, channel: %d" % (header['channel_mask'], chan))

            if chanmask & 0x1:
                self.channels[chan] = packetteChannel(0, np.empty([0], dtype=np.int16), self.run)

            # Advance to the next place in the mask
            chanmask >>= 1
            chan += 1

    def prettyid(self):
        return ':'.join(self.run.board_id.hex()[i:i+2] for i in range(0,12,2))
    
    def __str__(self):
        board_id = self.prettyid()
        msg = "\nBoard MAC:\t %s\n" % board_id
        msg += "Event number:\t %d\n" % self.event_num
        msg += "Timestamp:\t %d\n" % self.trigger_low
        msg += "Channels:\n "

        chans = list(self.channels.keys())
        drsstr = ''
        for drs in range(8):
            drsstr += "\tDRS%d: [" % (drs+1)
            for chan in range(8):
                if drs*8+chan in chans:
                    drsstr += '%3d' % (drs*8+chan)
                else:
                    drsstr += ' . '
            drsstr += " ]\n"

        msg += drsstr
        return msg

class packetteRun(object):

    # Initialize and load the files
    def __init__(self, fnames, SCAView=False):

        # NOTE: fnames is assumed to be sorted in the order you want to deinterlace in!
        # Check for stdin
        self.header_size = packette_transport.size
        self.board_id = None
        self.orderedEventList = []
        self.offsetTable = OrderedDict()
        self.eventCache = OrderedDict()

        self.SCAView = SCAView
        
        # We usually expect lists.  If its a one off, check for special conditions.
        # If not, wrap it in a list
        if not isinstance(fnames, list):

            if fnames == '-':
                raise Exception("Cannot seek on stdin.  Start taking data to a backing file, and specify that file to work in real-time")

            # Try to parse fnames as a python socket specifier
            # e.g. ('127.0.0.1', 3445) 
            if (isinstance(fnames, tuple)
                and len(fnames) == 2
                and isinstance(fnames[0], str)
                and isinstance(fnames[1], int)):

                # (Parent will not use s or tmpfile)
                
                # Let the OSError exception propogate upwards if it happens
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

                # Timeout after 1 second
                s.settimeout(1.0)
                
                # Listen to the socket
                s.bind(fnames)

                # Socket is up, create the filename for the backing file
                # and open it (so we make sure not to race here)
                fnames = ['packetteRun_%s_%d_%f.dat' % (fnames[0], fnames[1], time.time())]

                # Open the destination file as unbuffered, so each time we write
                # the actual data goes into the file
                tmpfile = open(fnames[0], 'wb', 0)

                # Stash parent pid
                ppid = os.getpid()
                
                # Now fork
                pid = os.fork()
                if not pid:
                    # We are childlike, dump everything into the file
                    try:
                        while True:                            
                            try:
                                # Since its a datagram, this will block until timeout or an entire packet is pulled
                                # from the underlying buffers

                                # XXX DOES NOT PERFORM SEQUENCE NUMBER CHECKS, NEEDS TO
                                stuff = s.recv(4096)
                                tmpfile.write(stuff)
                            except socket.timeout as e:
                                # If the parent has died, we should die too
                                if not os.getppid() == ppid:
                                    exit(0)
                    except OSError as e:
                        print("Data capture process encountered trouble: ", e)
                    finally:
                        # Always close out the backing file
                        tmpfile.close()
                else:
                    # We are the parent
                    print("Successfully forked data capture PID %d, writing to %s..." % (pid, fnames[0]), file=sys.stderr)
            else:
                # Wrap it in a list
                fnames = [fnames]
                
        # Now the previous machinery should work, just on the backing file
        self.fnames = fnames
        self.fps = {}
        self.fp_indexed = {}
        
        # This stores integer handles to file pointers that back the event data
        self.fps = { n : open(f, 'rb') for n,f in enumerate(fnames)}

        # This stores the most recent position where a header read failed
        # (used to update the index on the fly)
        self.fp_indexed = { n : 0 for n in range(len(fnames))}

        # 
        # UUU Need to save state to index files, so you don't need to rebuild the
        # index every time.
        #

        # UUU We should really be using pool here to index large data sets in parallel
        
        # See if we keep the data on the HD/inside OS buffers
        for fhandle,fp in self.fps.items():

            # Didn't seem to work...
            # Make sure we get the most recent jazz
            # os.fsync(fp.fileno())

            # Send it the 0 index, since this is the first time we are building the index
            # parseOffsets mutates the offsetTable directly
            self.parseOffsets(fp, fhandle, 0)
            print("packette_stream.py: built event index for %s" % fnames[fhandle], file=sys.stderr)

    def parseOffsets(self, fp, fhandle, index):
        # This will index event byte boundaries in the underlying stream
        # Lookups can then be done by seeking in the underlying stream
        # Start loading in event data
        prev_event_num = -1
        neweventcnt = 0

        #offsetTable = {}

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
                print("packette_stream.py: Expecting %s but just read %s..." % (self.board_id, header['board_id']), file=sys.stderr)
                
                raise Exception("ERROR: Heterogenous board identifiers in multifile event stream.\n " \
                                "\tOutput from different boards should be directed to\n " \
                                "\tdistinct packette instances on disjoint port ranges")

            # This logic is being weird.  Be explicit.
            if index == self.header_size or prev_event_num < header['event_num']:

                # Sanity check
                if header['event_num'] in self.offsetTable:
                    raise Exception("Event number collision!", header['event_num'], (fhandle, index - self.header_size))
                
                # Return a tuple with the stream and the byte position within the stream
                self.offsetTable[header['event_num']] = (fhandle, index - self.header_size)

                # Do an event-number sorted insertion
                bisect.insort(self.orderedEventList, header['event_num'])

                # Keep track that we've passed an event boundary
                prev_event_num = header['event_num']

                # Count
                neweventcnt += 1
                
            # Increment the index by the size of this packet's payload
            index += header['num_samples'] * SAMPLE_WIDTH

            # Seek this amount
            fp.seek(index)

        # Set the most recently successful read
        self.fp_indexed[fhandle] = index

        # Return it
        return neweventcnt
    
    # An accessor method to hide the variable
    def getArrivalOrderedEventNumbers(self):
        return self.orderedEventList
    
    # Time ordered views return capacitor DRS4_STOP when requesting index 0
    # Capacitor ordered views return capacitor 0 when requesting index 0
    def setSCAView(self, flag):

        # Nop
        if flag == self.SCAView:
            return

        # Set it
        self.SCAView = flag

        # Switch everyone's masks
        # Rebuild everyone's in the event' cache's channel cache!
        for event in self.eventCache.values():
            for chan in event.channels.values():
                # Convert mask values
                if flag:
                    chan.masksToSCA()
                else:
                    chan.masksToTime()

                # Rebuild cache
                chan.buildCache()

        # (subsequently added events will automatically be channel cached correctly)
        
    def loadEvent(self, event_num):

        # First check cache
        try:
            return self.eventCache[event_num]
        except KeyError as e:
            # Wasn't in there
            print("DEBUG (packette_stream.py): cache MISS on event #", event_num)
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
                event = packetteEvent(header, self)
            
            # If we've read past the event, return the completed event
            if prev_event_num < header['event_num']:
                break
            
            # Check to see if this channel is actually in the mask
            if header['channel_mask'] & (1 << header['channel']) > 0:
                #print("Num samples: ", header['num_samples'])
                
                # Populate the channel data from this transport packet
                chan = event.channels[header['channel']]

                # Is this the first data for this channel? 
                if len(chan) == 0:
                    # Make a new block of memory
                    chan.drs4_stop = header['drs4_stop']
                    chan.payload = np.zeros(header['total_samples'], dtype=np.int16)
                    chan.length = header['total_samples']

                    # Add a 5 sample symmetric mask around the stop sample
                    maskWidth = 15
                    if self.SCAView:
                        chan.mask(header['drs4_stop'] - maskWidth, header['drs4_stop'] + maskWidth)
                    else:
                        chan.mask(-maskWidth, maskWidth)

                # Now, since the underlying stream may be growing, we might have gotten a header
                # but we don't have enough underlying data to finish out the event here
                capacitors = fp.read(header['num_samples']*SAMPLE_WIDTH)

                # Verify that we *got* this amount
                if not len(capacitors) == header['num_samples']*SAMPLE_WIDTH:

                    # We didn't get this payload yet, that's fine.
                    # It'll work on the next read, when we seek back to the last
                    # unprocessed header.
                    break

                # Read the payload from this packet
                payload = np.frombuffer(capacitors, dtype=np.int16)

                # Write the payload at the relative offset within the numpy array
                # XXX This will glitch if you try to give a rel_offset into a
                #     block that is the block length you are writing
                #     The firmware should never do this to you though...
                # print("payload of length %d written to slice %d:%d" % (len(payload), header['rel_offset'], header['rel_offset'] + header['num_samples']))

                chan.payload[header['rel_offset']:header['rel_offset'] + header['num_samples']] = payload

                # print("\tHEY Got a rel_offset: ", header['rel_offset'], file=sys.stderr)
                # Debug (set the final relative offset)
                chan.rel_offset = header['rel_offset']

        # Now we've loaded all the payloads, build the cache
        for data in event.channels.values():
            data.buildCache()
            
        # Add this event to the event cache, removing something if necessary
        self.eventCache[event.event_num] = event

        if len(self.eventCache) > EVENT_CACHE_LENGTH:
            # Get rid of the oldest thing in the cache
            self.eventCache.popitem(last=False)
        
        # Return this event
        return event

    # Implement this as a dictionary for fast accesses
    def __getitem__(self, eventnum):
        return self.loadEvent(eventnum)

    # For underlying streams that are growing, we can update the index
    def updateIndex(self):
        start = time.time()
        neweventcnt = 0
        
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
            neweventcnt += self.parseOffsets(fp, fhandle, self.fp_indexed[fhandle])

        stop = time.time()

        # Return how many new events and how long it took to index them
        return (neweventcnt, stop - start)
    
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
        for i in self.offsetTable.keys():
            yield self.loadEvent(i)

# A human-readable view of the (cached) array state
def dumpCachedView(array, width=3):
    #msg = '# ' + ('SCA (capacitor-ordered) view' if self.run.SCAView else 'DRS4_STOP (time-ordered) view') + "\n"
    msg = ''
    step = 1 << width
    # Make a nice mask display
    for n in range(1024 >> width):
        msg += "caps [%4d, %4d]: %s\n" % (step*n, step*(n+1) - 1, array[step*n:step*(n+1)])

    return msg

def dumpPayload(array, width=3):
    msg = ''
    step = 1 << width
    # Make a nice mask display
    for n in range(len(array) >> width):
        msg += "caps [%4d, %4d]: %s\n" % (step*n, step*(n+1) - 1, array[step*n:step*(n+1)])

    # Print out the rest if we need to
    if not (len(array) >> width) << width == len(array):
        msg += "caps [%4d, %4d] :%s\n" % ( (len(array)>>width) << width, len(array) - 1, array[(len(array)>>width)<<width:])
    
    return msg

# Testing stub
def test():
    events = packetteRun(sys.argv[1:], SCAView=True)
    print("Loaded %d events" % len(events))

    import pickle
    pickle.dump(events, open("pickledPacketteRun.dat", "wb"))

    # Look at it using native dumps
    for event in events:
        for chan,data in event.channels.items():
            print("event %d, channel %d\n" % (event.event_num, chan))
            #print(data, dumpCachedView(data.cachedView))

            # Looks like it works!
            
            # Test your cleverness with the masking
            flags = (data.cachedView.copy()) & 0xF
            flagged = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

            print(dumpCachedView(flagged))
            
            # Kill the mask
            # data.clearMasks()
            #print(data, dumpCachedView(data.cachedView))

            # Test it again
            flags = (data.cachedView.copy()) & 0xF
            flagged = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

            print(dumpCachedView(flagged))

    # Now switch to time ordered
    events.setSCAView(False)
    
    # Look at it using native dumps
    for event in events:
        for chan,data in event.channels.items():
            print("event %d, channel %d\n" % (event.event_num, chan))
            #print(data, debugChannel(data.cachedView))

            # Looks like it works!
            
            # Test your cleverness with the masking
            flags = (data.cachedView.copy()) & 0xF
            flagged = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

            print(dumpCachedView(flagged))
            
            # Kill the mask
            # data.clearMasks()
            #print(data, dumpCachedView(data.cachedView))

            # Test it again
            flags = (data.cachedView.copy()) & 0xF
            flagged = 1 - (((flags & 0x8) >> 3) | ((flags & 0x4) >> 2) | ((flags & 0x2) >> 1) | (flags & 0x1))

            print(dumpCachedView(flagged))

    # Lets see how big it is was a 100 event cache
    pickle.dump(events, open("pickledPacketteRun.dat", "wb"))
            
    print('')
    
    # import time
    # time.sleep(5)

    # # Test an update
    # events.updateIndex()

    # # Test the pickle
    # events = pickle.load(open("pickledPacketteRun.dat", "rb"))
    # print("Loaded %d events" % len(events))

    
# # Invoke it
# test()    

