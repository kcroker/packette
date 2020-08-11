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

// Maximum payload size (in bytes)
#define MAX_PAYLOAD 1024

// How many bytes per sample (2 for 12 bit ADC)
#define SAMPLE_RESOLUTION 2

// How many channels?
#define NUM_CHANNELS 64

//
// This quantity is only needed during assembly and is omitted otherwise
//
struct assembly {
  unsigned long cap_offset;     // Writing offset during assembly
};

//
// In the final data stream, they will only occur once at the start of the data.
// In particular, seqnum will be the starting event number.
//
struct header {
  unsigned long seqnum;         // This now monotonically increases across events and individual fragmented packets.
  unsigned long channel_mask;   // 64 bit mask on which channels were enabled (to distinguish with zero suppression)
  unsigned long roi_width;      // How large the ROI mode was (for indexing into the data file)
};

// 8 bytes
struct channel_block {
  unsigned long channel;        // This is the device channel
  unsigned long drs4_stop;      // This is where the sampling stopped.  Sits here because there are many DRS4s.
  unsigned int samples[0];      // This will always be roi_length when reconstructed or some fragment length, divisible by 8
};

//
// These are quantities that will be shipped out on each packet
// for fastest reconstruction.
//
struct packette_raw {
  struct assembly assembly;
  struct header header;
  struct channel_block data;
};

// 
// MACROS
//

// Returns a pointer to the head of the Nth event
#define EVENT(N, packet) ( (unsigned short *) ( (packet).data + ( (sizeof struct channel_block) + (packet).roi_width) * active_channels * (N) ) )

// Returns a pointer to the head of the requested channel of the Nth event if present, otherwise returns NULL
#define CHANNEL(channel, packet)  ( (unsigned short *) ( (packet).channel_map[(channel)] < 0 ? 0x0 : (packet).channel_map[(channel)]*( (packet).roi_width + (sizeof struct channel_block)) ) )

//
// This is the format of the final written file
//
struct packette_processed {

  struct header header;

  // Convenience quantities
  unsigned char active_channels;
  char channel_map[NUM_CHANNELS];
		   
  // Here be dragons
  struct channel_block data[0];

  //
  // For example, suppose you are interested in the 7th event, channel 8, use the macro:
  //
  //   unsigned short *ptr;
  //   ptr = EVENT(7, packet) + CHANNEL(9, packet);
  //
  
  // WARNING: active_channels must be set globally!
  //
  
  //   
  //
  // 
  // For example, if you want to read the 16 bit short describing the 109th capacitor of the 8th channel, relative to the stop sample:
  //    val = *( (unsigned short *) (event.data + event.header.roi_width*event.channel[8] + 109*SAMPLE_RESOLUTION))
  //
  // Or get a pointer to that channels data
  
};
 

//
// GLOBALS (because short and simple, the UNIX way)
//
// Note that things are unsigned long because we want to avoid implicit casts
// during computation.
void (*process_packet_fptr)(struct packette *p);
unsigned long active_channels;
unsigned char channel_map[MAX_CHANNELS];
unsigned long fragments_per_channel;
unsigned long current_evt_seqnum;

unsigned long *emptyBlock;


//
// Build channel map.  Returns the number of active channels
// Assumes channel map has been initialized.
//
unsigned long buildChannelMap(unsigned long mask) {

  unsigned long active = 0;
  unsigned char i = 0;

  // Note that this short circuits as soon
  // as all the high bits are dead! ::pride::
  for(; mask; mask >> 1) {

    // Check the LSB
    if(mask & 0x1)
      channel_map[i++] = ++active;
  }

  return active;
}

//
// Perform initialization based on the first packet received
//
void preprocess_first_packet(struct packette *p) {

  unsigned long mask;
  
  // Build the channel map, compute the number of active channels
  active_channels = buildChannelMap(p->channel_mask);
  
  // Compute the fragments per channel
  //
  // Standard idiom for positive integers:
  // https://stackoverflow.com/questions/2422712/rounding-integer-division-instead-of-truncating
  //
  // AAA (assuming that there is only one ROI region per channel)
  fragments_per_channel = (p->roi_width * SAMPLE_RESOLUTION + (MAX_PAYLOAD - 1)) / MAX_PAYLOAD
  
  // Allocate the placeholder block
  if (! emptyBlock = (unsigned long *) malloc(p->roi_width) ) {
    exit(4);
  }

  // Assign once, decrement once
  for(i = (roi_width >> 3); i > 0;)
    emptyBlock[--i] = NO_DATA_FLAG_4X;

  // Set the process function to subsequent packets
  // (this way we avoid an if every time to see if we are first)
  process_packet_fptr = &process_packet;

  // Process this first packet!
  (*process_packet_fptr)(p);
}
				  
/* void process_packet(struct packette *p) { */

/*   // If we exceeded the boundary for the next event? */
/*   next_event_seqnum = current_event_seqnum + (active_channels * fragments_per_channel); */

/*   // Do we ship? */
/*   if(p->seqnum >= next_event_seqnum) { */

/*     // Oh yeah, we ship */
/*     flushAndResetBuffer(); */
/*   } */
  
/*   // Check for out of ordering */
/*   delta = p->seqnum - prev_seqnum; */
/*   if(delta < 0) { */

/*     // Output this onto the jumbled stream for Stage II */
/*     stashJumbled(p); */

/*     // Write placeholder block of the correct length */
/*   } */
/* } */

/* void cleanup(void) { */

/*   free(emptyBlock); */
/* } */

int main(int argc, char **argv) {

  // Socket stuff
  int sockfd, retval, i;
  struct sockaddr_in addr;
  struct mmsghdr msgs[VLEN];
  struct iovec iovecs[VLEN];
  char bufs[VLEN][BUFSIZE+1];
  struct timespec timeout;

  // Multiprocessing stuff
  pid_t pid;
  pid_t *kids;
  
  // Set the initial packet processing pointer to the preprocessor
  process_packet_fptr = &preprocess_first_packet;

  // Initialize the channel map
  for(i = 0; i < MAX_CHANNELS; ++i)
    channel_map[i] = -1;

  //
  // No IPC is required between children
  // but we want the parent to receive the Ctrl+C and clean up the children.
  //
  children = atoi(argv[3]);
  pid = 1;
  if( !kids = (pid_t *)malloc(sizeof(pid_t) * children)) {
    perror("malloc()");
    exit(FUCK_YOU);
  }
  
  //
  // SPAWN
  // Loop exits when:
  //    pid == 0 (i.e. you're a child)
  //           OR
  //    children == 0 (i.e. you've reached the end of your reproductive lifecycle)
  // Implemented as a negation.
  //
  // Note children is mutated in second position and AND short circuits
  // So if we've made all of our kids, then children
  while(pid && --children)
    kids[children] = pid = fork();

  ////////////////// FORKED ////////////////////
  if(!pid) {
    ////////////////// CHILD ///////////////////
    print("I am a forked child!");
    exit(0);

    // Open the socket
  
    // Starting event sequence number is given at the command line
    // (write a C interface for eevee for quick register reads/writes)
    //
    // Code adapted from: man 2 recvmmsg, EXAMPLE

#define VLEN 10
#define BUFSIZE 200
#define TIMEOUT 1  

    /* // Get a socket */
    /* sockfd = socket(AF_INET, SOCK_DGRAM, 0); */
    /* if (sockfd == -1) { */
    /*   perror("socket()"); */
    /*   exit(EXIT_FAILURE); */
    /* } */

    /* sa.sin_family = AF_INET; */

    /* // Get the given IP and port from strings */
    /* // Set the port (truncate, base 10, ignore bs characters) */
    /* // XXX Don't check for errors ;) */
    /* inet_pton(AF_INET, argv[1], &(sa.sin_addr)); */
    /* sa.sin_port = htons(strtoul(argv[2], NULL, 10)); */

    /* // Why does this always have an explicit cast? */
    /* if (bind(sockfd, &sa, sizeof(sa)) == -1) { */
    /*   perror("bind()"); */
    /*   exit(EXIT_FAILURE); */
    /* } */

    /* // Now we do the magic. */
    /* // We read in directly to packet buffers */
    /* // That we will cast as structs */
    /* memset(msgs, 0, sizeof(msgs)); */
    /* for (i = 0; i < VLEN; i++) { */
    /*   iovecs[i].iov_base         = bufs[i]; */
    /*   iovecs[i].iov_len          = BUFSIZE; */
    /*   msgs[i].msg_hdr.msg_iov    = &iovecs[i]; */
    /*   msgs[i].msg_hdr.msg_iovlen = 1; */
    /* } */

    /* timeout.tv_sec = TIMEOUT; */
    /* timeout.tv_nsec = 0; */

    /* // Now pull packets in bulk */
    /* // Pull as many as will fit in L2 cache on your platform */
    /* while(1) { */

    /*   retval = recvmmsg(sockfd, msgs, VLEN, 0, &timeout); */
    /*   if (retval == -1) { */
    /* 	perror("recvmmsg()"); */
    /* 	exit(EXIT_FAILURE); */
    /*   } */

    /*   printf("%d messages received\n", retval); */
    /*   for (i = 0; i < retval; i++) { */
    /* 	bufs[i][msgs[i].msg_len] = 0; */
    /* 	printf("%d %s", i+1, bufs[i]); */
    /*   } */
    /* } */    
  }
  else {
    ////////////////// PARENT //////////////////
    printf("I am the parent.  These are my kids");
    children = atoi(argv[3]);
    
    while(--children)
      printf("%d\n", kids[children]);

    exit(0);
  }
  
  // Even though this will get torn down on process completion,
  // come correct.
  free(kids);
  //  cleanup();
}   
