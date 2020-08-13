// DRS4 specific stuff
#define CAP_LEN 1024
#define CAP_LEN_DIV2 512

// power of 2 for the receiving architecture pointer width
#define ARCHITECTURE_WIDTH 8

#define OVERFLOW_FLAG 0x0001
#define UNDERFLOW_FLAG 0x0002
#define NO_DATA_FLAG 0x0004

// Used for writing 8 bytes of no data quickly
#define NO_DATA_FLAG_4X 0x0004000400040004

// Maximum fragment size (in samples)
#define MAX_FRAGMENT_WIDTH 512

// How many bytes per sample (2 for 12 bit ADC)
#define SAMPLE_WIDTH 2

// How many channels?
#define NUM_CHANNELS 64

#if (NUM_CHANNELS > 64)
#error "In this version, channel masks are encoded using a 64-bit long."
#endif

//
// Run header - that allows reproduction of board state.
// This is a separate thing.
//

// 
// Spaketh the greybeard ESR:
//
// "The riskiest form of packing is to use unions. If you know that certain fields in your structure are never used in combination with certain other fields, consider using a union to make them share storage. But be extra careful and verify your work with regression testing, because if your lifetime analysis is even slightly wrong you will get bugs ranging from crashes to (much worse) subtle data corruption."
//
//    http://www.catb.org/esr/structure-packing/
//
// Justification:
//   We use unions because we don't need all the values *at the same time*.
//   Later processing steps can grab or cast specific offsets of the buffer.
//

//
// These quantities are only needed during assembly and are discarded  
//
// 16 bytes
struct assembly {
  
  //
  // 2 bytes: relative sample offset (used during assembly)
  // 6 bytes: board MAC address (magic)
  //
  // This lets us keep an 8 byte alignment, and also
  // immediate rip out what we need for assembly in the first 2 bytes
  // of the packed downstream[8].
  //
  union {
    unsigned short rel_offset;    // Relative sample offset, for writng during assembly
    unsigned char downstream[8];  
  } header;
  
  unsigned long seqnum;           // This now monotonically increases across events and individual fragmented packets.
};

// 16 bytes
struct header {

  //
  // 2 bytes: event number (used during assembly)
  // 4 bytes: trigger time low
  // 2 bytes: RESERVED
  //
  // This lets us keep an 8 byte alignment, and also
  // immediate rip out the eventnumber from the first 2 bytes
  // of the packed downstream[8].
  //
  union {
    unsigned short eventnum;      
    unsigned char downstream[8]; // Block of packed data for later use
  } event;
  
  unsigned long channel_mask;    // Dyanmical: which channels were on in this event
};

// 8 bytes + length
struct channel {

  //
  // 2 bytes: The number of samples (used during assembly)
  // 1 byte:  This is the device channel
  // 2 bytes: This is where the sampling stopped.  Sits here because there are many DRS4s.
  // 3 bytes: RESERVED 
  //
  // This lets us keep an 8 byte alignment, and also
  // immediately rip out the number of samples from the
  // first 2 bytes of the packed downstream[8].
  //
  union {
    unsigned short num_samples;  // This is the ROI width, it can change at the channel level
    unsigned char downstream[8];
  } header;

  unsigned short samples[0];     // 0 length.  Casted pointer to the first sample
};

//
// These are quantities that will be shipped out on each packet
// for fastest reconstruction.
//
// 40 byte header - x86 64bit cache line is 64 bytes, so we fit.
//
struct packette_transport {
  struct assembly assembly;    // 16 bytes
  struct header header;        // 16 bytes
  struct channel channel;      // 8 bytes + (variable)roi_width*SAMPLE_WIDTH
};

#define BUFSIZE (sizeof(struct packette_raw) + MAX_FRAGMENT_WIDTH*SAMPLE_WIDTH)

////////////////////// CONSTRAINTS ////////////////////////
//
//    roi_width * SAMPLE_WIDTH must be a multiple of 8
//
//


//
// XXX This is the format of the final written file
//

struct packette_processed {

  struct header header;                      // 
  unsigned long channel_map[NUM_CHANNELS];
		   
  // Here be dragons
  struct channel_block data[0];  
};

// 
// MACROS
// XXX (these are probably broken right now)
 
// Returns a pointer to the head of the Nth event
#define EVENT(N, packet) ( (unsigned short *) ( (packet).data + ( (sizeof struct channel_block) + (packet).roi_width) * active_channels * (N) ) )

// Returns a pointer to the head of the requested channel of the Nth event if present, otherwise returns NULL
#define CHANNEL(channel, packet)  ( (unsigned short *) ( (packet).channel_map[(channel)] < 0 ? 0x0 : (packet).channel_map[(channel)]*( (packet).roi_width + (sizeof struct channel_block)) ) )

