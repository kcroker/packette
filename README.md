
# Packette v1.0
<img src="http://www.phys.hawaii.edu/~kcroker/packette/fp.png" width="50%"/>

_Chaotic good female fire elemental, carries and rips packets from sockets at blazing speed._

## Overview
packette is a highly robust UDP protocol and client suite for extremely rapid data capture and inspection.
The main tools are

* `packette` : L1 cache-optimized multiprocess C program which moves incoming packets 
from sockets to files, in order
* `packette-merge` :  (optional) integrates unordered packets into existing ordered streams
* `packette_stream.py` : provides a list-like API for Python 3 programs by indexing and caching the underlying OS streams.
* `packette_browse.py` : lightweight shell for inspection and visualization of packette data streams

## Packet structure

Coming soon.  For now, look in `packette.h`.

## Usage Examples

The typical usage is to start `packette` and then monitor the data stream.  
`packette` will dump data to a directory `rawdata` in the current working directory and will fail if this directory does not exist.
In its default operation, `packette` uses ncurses to display real-time statistics of packets-per-second (pps)
and bytes-per-second pushed to the OS.  
So, a typical usage is to start `packette` in one terminal window

```bash
   $ ./packette 10.0.6.254 -f testing
```
without any event count limits.  The IP adresss specifies the bind address, and the default port 1338 will be used.  
The flag `-f` sets the data stream prefix for files written into `rawdata`.
Any files that exist are overwritten.
Data, as it arrives, can then be inspected using `packette_browse.py`

```bash
   $ ./packette_browse.py rawdata/testing*
```

`packette_browse.py` implements a shell with TAB autocompletion, online help, and command/history editting.
An example shell command is as follows.
To graph the most recently arrived event's channels 0-31

```
   Event #7 @ 5 (packette) graph 0-31
```

Notice that the prompt gives the current event number and also its position with the stream.
The event number is determined by the data stream and board itself, where as the position within the 
stream is determined by receipt order at the client.
Underlying instructions can be sent to board control software.  
Consider the following 

```
   Event #7 @ 5 (packette) cmd -c 0x00000000000000ff -N 10 -r 500 10.0.6.212
   Event #7 @ 5 (packette) refresh
   Event #17 @ 17 (packette) graph 0-31
```

This example assumes use of packette with the Ultraltyics A2x series boards.  
It does the following:

1. set the channel mask and request 10 soft triggers at 500 Hz from an A2x board at IP 10.0.6.212
2. update the stream index and jump to the most recently received event
3. graph the first 32 channels

The final operation will only reflect the 8 channels of data present.
Individual channel data, including unmasked raw payloads, masks, and stop samples can be viewed with

```
   Event #7 @ 5 (packette) channel 5
```

The following example places an A2x series board into ADC test-pattern mode 'ramp', sends a single soft trigger, and graphs all channels:

```
   Event #7 @ 5 (packette) cmd -c 0xffffffffffffffff -N 1 --adcmode ramp 10.0.6.212
   Event #7 @ 5 (packette) refresh
   Event #8 @ 6 (packette) graph 0-63
```

## Taking a pedestal

Right now, this process is not streamlined, but its easy enough.
In this example, we will use 4 processes at every step.
In packette, packet reception and processing are decoupled, so first start `packette` in
a terminal to monitor the acquisition
```
   $ ./packette 10.0.6.254 -f pedestal_waveforms -t 4
```
This example will spawn 4 processes to listen on 4 UDP ports, respectively. 
Then, in a different terminal, request the raw waveforms
```
   $ ./A2x_tool.py 10.0.6.97 -N 10000 -r 700 -c 0x00000000ffffffff -t 4
```
This will request 10k waveforms, for channels 0-31, from the board at 10.0.6.97, at a soft-triggered rate of 700Hz,
and will instruct the board to distribute them across 4 UDP ports.
You'll see the data flowing into `packette`.
When `A2x_tool` is done, Ctrl+C `packette`.

Now you can run generate the pedestal in parallel
```
   $ time ./pedestal_calibration.py rawdata/pedestal_waveforms_10.0.6.254_*.ordered
```
The leading `time` is not required, but you can see how fast it goes.
I can get a 1% pedestal for 32 channels in ~7s on a computer literally pulled out of the garbage.
Awkwardly right now, the pedestal file generated is always called `boardid.pedestal` (sorry).
To inspect performace, run
```
   $ ./describe_pedestal.py boardid.pedestal > ascii_pedestal
```
The `ascii_pedestal` will have a block of data for each channel, with columns: capacitor #, mean, RMS, channel (for convenience), counts.
This can be visualized in `gnuplot`, for example
```
   gnuplot> set term x11
   gnuplot> plot "ascii_pedestal" every :::4::4 using 1:2:3 with errorbars
```
This will plot the mean values with RMS as errorbars for the 5th channel appearing in the pedestal description.
For our particular `pedestal_waveforms`, this will be channel 4.
