#define _GNU_SOURCE

// Linux process scheduling
#include <sched.h>

// Sockets
#include <netinet/ip.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>

// Multiprocess
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

// Signals
#include <signal.h>

// Errs
#include <errno.h>

// Time
#include <time.h>

// Shared memory (for interprocess comms without IPC)
#include <sys/mman.h>

// For total fluff
#include <ncurses.h>

// Local stuff
#include "packette.h"

#define DEBUG

///////////////////////////// GLOBALS /////////////////////////

// Note that things are unsigned long because we want to avoid implicit casts
// during computation.
unsigned long (*process_packets_fptr)(void *buf,
				      struct mmsghdr *msgs,
				      int vlen,
				      FILE *ordered_file,
				      FILE *orphan_file,
				      uint64_t *prev_seqnum,
				      uint32_t *prev_event_num);

unsigned long *emptyBlock;

// This is used to signal that we should cleanup
volatile sig_atomic_t interrupt_flag = 0;

//
// This is the sickness
//
// Made with:
//   http://patorjk.com/software/taag/
//
char *packette_logo =
"  (                            )                                \n"
"  )\\ )     (         (      ( /(          *   )    *   )        \n"
" (()/(     )\\        )\\     )\\())  (    ` )  /(  ` )  /(   (    \n"
"  /(_)) ((((_)(    (((_)  |((_)\\   )\\    ( )(_))  ( )(_))  )\\   \n"
" (_))    )\\ _ )\\   )\\___  |_ ((_) ((_)  (_(_())  (_(_())  ((_)  \n"
" | _ \\   (_)_\\(_) ((/ __| | |/ /  | __| |_   _|  |_   _|  | __| \n"
" |  _/    / _ \\    | (__    ' <   | _|    | |      | |    | _|  \n"
" |_|     /_/ \\_\\    \\___|  _|\\_\\  |___|   |_|      |_|    |___| \n";

                                                               
//
// Build channel map.  Returns the number of active channels
// Assumes channel map has been initialized.
//
unsigned long buildChannelMap(unsigned long mask, unsigned char *channel_map) {

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
// PACKET PROCESSORS
//
unsigned long nop_processor(void *buf,
			    struct mmsghdr *msgs,
			    int vlen,
			    FILE *ordered_file,
			    FILE *orphan_file,
			    uint64_t *prev_seqnum,
			    uint32_t *prev_event_num) {

  unsigned long bytes;
  
  // Oh yeah, we totally processed your packets
  bytes = 0;
  while(vlen--)
    bytes += msgs[vlen].msg_len;
  
  return bytes;
}


unsigned long buffer_dump_processor(void *buf,
				    struct mmsghdr *msgs,
				    int vlen,
				    FILE *ordered_file,
				    FILE *orphan_file,
				    uint64_t *prev_seqnum,
				    uint32_t *prev_event_num) {

  //
  // Writes the entire message buffer at once, including deadspace not necessarily
  // consumed by the packets.
  //
  fwrite(buf,
	 BUFSIZE,
	 vlen,
	 ordered_file);

  return BUFSIZE;
}

unsigned long payload_dump_processor(void *buf,
				     struct mmsghdr *msgs,
				     int vlen,
				     FILE *ordered_file,
				     FILE *orphan_file,
				     uint64_t *prev_seqnum,
				     uint32_t *prev_event_num) {

  struct packette_transport *ptr;
  unsigned long bytes;

  bytes = 0;
  
  //
  // This does nothing but write packet headers and payloads to the ordered file.
  // (This removes buffer garbage)
  //
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // Blast
    fwrite(buf,
	   ptr->channel.num_samples*SAMPLE_WIDTH,
	   1,
	   ordered_file);
    
    bytes += ptr->channel.num_samples*SAMPLE_WIDTH;
    
    // Get the next one
    buf += BUFSIZE;
  }

  return bytes;
}

unsigned long debug_processor(void *buf,
			      struct mmsghdr *msgs,
			      int vlen,
			      FILE *ordered_file,
			      FILE *orphan_file,
			      uint64_t *prev_seqnum,
			      uint32_t *prev_event_num) {

  struct packette_transport *ptr;
  unsigned int i;
  
  //
  // This outputs the headers that come in off the pipe
  //
  char *output =
    "Packette Transport Header:\n"
    "---------------------------\n"
    "Board id:\t\t\t%.2x:%.2x:%.2x:%.2x:%.2x:%.2x\n"
    "Relative offset:\t\t%u\n"
    "Sequence number:\t\t%lu\n"
    "Event number:\t\t\t%u\n"
    "Trigger timestamp (low):\t%u\n"
    "Channel mask:\t\t\t%.2x %.2x %.2x %.2x %.2x %.2x %.2x %.2x\n"
    "Samples (this fragment):\t%u\n"
    "Channel number:\t\t\t%u\n"
    "Total samples (all fragments):\t%u\n"
    "DRS4 stop:\t\t\t%u\n"
    "--------- COMPUTED ---------\n"
    "Payload length (bytes):\t%u\n\n";
  i = 0;
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    fprintf(ordered_file,
	    output,
	    ptr->assembly.board_id[0], ptr->assembly.board_id[1],
	    ptr->assembly.board_id[2], ptr->assembly.board_id[3],
	    ptr->assembly.board_id[4], ptr->assembly.board_id[5],
	    ptr->assembly.rel_offset,
	    ptr->assembly.seqnum,
	    ptr->header.event_num,
	    ptr->header.trigger_low,
	    ((unsigned char *)&(ptr->header.channel_mask))[7],
	    ((unsigned char *)&(ptr->header.channel_mask))[6],
	    ((unsigned char *)&(ptr->header.channel_mask))[5],
	    ((unsigned char *)&(ptr->header.channel_mask))[4],
	    ((unsigned char *)&(ptr->header.channel_mask))[3],
	    ((unsigned char *)&(ptr->header.channel_mask))[2],
	    ((unsigned char *)&(ptr->header.channel_mask))[1],
	    ((unsigned char *)&(ptr->header.channel_mask))[0],
	    ptr->channel.num_samples,
	    ptr->channel.channel,
	    ptr->channel.total_samples,
	    ptr->channel.drs4_stop,
	    msgs[i].msg_len - sizeof(struct packette_transport));

    // Set the accounting
    *prev_seqnum = ptr->assembly.seqnum;
    *prev_event_num = ptr->header.event_num;
    
    // Get the next one
    buf += BUFSIZE;
    ++i;

  }
  
  return 0;
}

//
// This processor writes ordered headers and payloads to one file,
// and orphaned fixed width buffers to a different file for
// later qsort() and merge.  Ordering is determined by the
// sequence number.
//
unsigned long order_processor(void *buf,
			      struct mmsghdr *msgs,
			      int vlen,
			      FILE *ordered_file,
			      FILE *orphan_file,
			      uint64_t *prev_seqnum,
			      uint32_t *prev_event_num) {

  struct packette_transport *ptr;
  unsigned long bytes;
  unsigned int stride;
  
  // Start counter at zero
  bytes = 0;
  
  // Iterate over the packets we are given
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // Gotta check sequence number first
    // NOTE: short circuiting ||
    if(!*prev_seqnum || ptr->assembly.seqnum > *prev_seqnum) {

      // So we don't compute it twice (though the compiler
      // would probably do this for us)
      stride = sizeof(struct packette_transport) + ptr->channel.num_samples*SAMPLE_WIDTH;
      
      // Immediately write the packet with
      // only its payload to the output stream
      fwrite(buf,
	     stride,
	     1,
	     ordered_file);

      // Accounting
      bytes += stride;
      
      // Update previous successfully processed position
      *prev_seqnum = ptr->assembly.seqnum;
      *prev_event_num = ptr->header.event_num;
    }
    else {

      if(ptr->assembly.seqnum < *prev_seqnum) {
	// Immediately buffered write the fixed width
	// buffer to the orphans
	fwrite(buf,
	       BUFSIZE,
	       1,
	       orphan_file);
	
	// Accounting
	bytes += BUFSIZE;
      }

      // If we ended up here, it was a duplicate ==> drop it.
    }

    // Advance to the next packet
    buf += BUFSIZE;
  }

  // Return bytes written to disk
  return bytes;
}

//
// This processor randomly drops and shunts packets to the orphans.
// This is for testing unordered and lossy reassembly downstream
//
unsigned long abandonment_processor(void *buf,
				    struct mmsghdr *msgs,
				    int vlen,
				    FILE *ordered_file,
				    FILE *orphan_file,
				    uint64_t *prev_seqnum,
				    uint32_t *prev_event_num) {

  struct packette_transport *ptr;
  unsigned long bytes;
  unsigned int stride;
  uint8_t abandon;
  
  // Start counter at zero
  bytes = 0;

#define ABANDONMENT_CHECK 80

  // Iterate over the packets we are given
  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_transport *)buf;

    // See if a random number between 0 and 128 exceeds the check
    abandon = (rand() & 127) > ABANDONMENT_CHECK;
        
    if(!*prev_seqnum || (!abandon && (ptr->assembly.seqnum > *prev_seqnum))) {

      // So we don't compute it twice (though the compiler
      // would probably do this for us)
      stride = sizeof(struct packette_transport) + ptr->channel.num_samples*SAMPLE_WIDTH;
      
      // Immediately write the packet with
      // only its payload to the output stream
      fwrite(buf,
	     stride,
	     1,
	     ordered_file);

      // Accounting
      bytes += stride;
      
      // Update previous successfully processed position
      *prev_seqnum = ptr->assembly.seqnum;
      *prev_event_num = ptr->header.event_num;
      
    }
    else {

      if(abandon || ptr->assembly.seqnum < *prev_seqnum) {
	// Immediately buffered write the fixed width
	// buffer to the orphans
	fwrite(buf,
	       BUFSIZE,
	       1,
	       orphan_file);
	
	// Accounting
	bytes += BUFSIZE;
      }

      // If we ended up here, it was a duplicate ==> drop it.
    }

    // Advance to the next packet
    buf += BUFSIZE;
  }

  // Return bytes written to disk
  return bytes;
}

//
// Called when the child receives SIGINT
//
void flagInterrupt(int signum) {

  // This is a special volatile signal-safe integer type:
  //  https://wiki.sei.cmu.edu/confluence/display/c/SIG31-C.+Do+not+access+shared+objects+in+signal+handlers
  interrupt_flag = 1;
}

// Might want to divide this by 2 so that you don't take up all the L2 cache ;)
#define L2_CACHE 256000
#define TIMEOUT 1

// For runtime selectable packet processing pipeline
const unsigned char num_processor_ptrs = 3;
const char *processor_names[] = { "ordered_processor", "disordered_processor", "debug_processor" };
const unsigned long (*processor_ptrs[])(void *buf,
					struct mmsghdr *msgs,
					int vlen,
					FILE *ordered_file,
					FILE *orphan_file,
					uint64_t *prev_seqnum,
					uint32_t *prev_event_num) = {&order_processor, &abandonment_processor, &debug_processor};

int main(int argc, char **argv) {

  // Socket stuff
  int sockfd, retval, i;
  struct sockaddr_in sa;
  struct timespec timeout;
  unsigned int vlen;
  
  // recvmmsg() stuff
  struct mmsghdr *msgs;
  struct iovec *iovecs;
  void *buf;
  
  // Multiprocessing stuff
  pid_t pid;
  pid_t *kids;  
  unsigned char children, k;

  // Processor pinning stuff
  cpu_set_t  mask;

  // Argument parsing stuff
  int flags, opt;
  int nsecs, tfnd;
  unsigned short port;
  char *addr_str;
  unsigned int count;
  unsigned char packet_processor;
  
  // Signal handling stuff
  struct sigaction new_action, old_action;

  // Files and data output stuff
  FILE *ordered_file;              // Stage I reconstruction (ordered and stripped) output
  FILE *orphan_file;               // Stage II reconstruction (unordered, raw) output
  uint64_t prev_seqnum;            // Remembers the more recent sequence number written to the ordered stream
  struct tm lt;                    // For holding time stuff
  time_t secs;
  char tmp1[1024], tmp2[1024];
  unsigned int stash;
  uint32_t prev_event_num;
  
  // Shared memory for performance reporting
  struct timeval parent_timeout;   // timeval, timespec, tm ... ugh
  void *scratchpad;
  volatile unsigned long *packets_processed_ptr, *bytes_processed_ptr;
  unsigned long *previous_processed;
  unsigned long packets_processed, bytes_processed;
  char output[4906];
  float total_kpps, total_MBps, total_MB, total_Mp;
  
  // lol "basic" shit in C is annoying.
  // Default values
  port = 1338;
  children = 1;
  addr_str = 0x0;
  tmp1[0] = 0x0;
  ordered_file = 0x0;
  count = 0;
  packet_processor = 0;
  
  // Things for event counting
  prev_event_num = 0;
  stash = -1;
  
  /////////////////// ARGUMENT PARSING //////////////////
  
  while ((opt = getopt(argc, argv, "t:p:f:on:d:")) != -1) {
    switch (opt) {
    case 't':
      children = atoi(optarg);
      break;
    case 'p':
      port = atoi(optarg);
      break;
    case 'f':
      strncpy(tmp1, optarg, 1024); 
      break;
    case 'o':
      ordered_file = stdout;
      break;
    case 'd':
      packet_processor = atoi(optarg);
      if(packet_processor >= num_processor_ptrs) {
	fprintf(stderr, "ERROR: Unknown packet processor %d\n", packet_processor);
	exit(EXIT_FAILURE);
      }
      break;
    case 'n':
      // We add one here so that we can bypass on 0
      count = atoi(optarg) + 1;
      break;
    default: /* '?' */
      fprintf(stderr, "Usage: %s [-t threads] [-p base UDP port] [-f output file prefix] [-o dump to standard out] [-n event count] [-d debug select] BIND_ADDRESS\n",
	      argv[0]);
      exit(EXIT_FAILURE);
    }
  }

  // Sanity check
  if(ordered_file) {

    if(children > 1) {
      fprintf(stderr, "ERROR: Multiprocess dump to stdout is stupid.\n");
      exit(EXIT_FAILURE);
    }
    
    fprintf(stderr, "packette (parent): dumping to stdout...\n");
  }

  // Now grab mandatory positional arguments
  if(optind >= argc) {
    fprintf(stderr, "Expected bind address after options\n");
    exit(EXIT_FAILURE);
  }

  // Get the IP address
  addr_str = argv[optind];

  // Try to parse it out
  if(!inet_pton(AF_INET, addr_str, &(sa.sin_addr))) {
    perror("inet_pton()");
    exit(EXIT_FAILURE);
  }
    
  // Report what we've been asked to do
  fprintf(stderr,
	  "packette (parent): %d children will bind at %s, starting from port %d\n",
	  children,
	  argv[optind],
	  port);

  // Report how many packets
  if(!count) 
    fprintf(stderr,
	    "packette (parent): each child will listen until terminated with Ctrl+C\n");
  else
    fprintf(stderr,
	    "packette (parent): each child will receive data from %d events and then terminate\n", count - 1);

  ///////////////// PARSING COMPLETE ///////////////////
  
  // Set the initial packet processing pointer to the preprocessor
  process_packets_fptr = processor_ptrs[packet_processor];

  // Now compute the optimal vlen via truncated idiv
  vlen = L2_CACHE / BUFSIZE;
  fprintf(stderr,
	  "packette (parent): Determined %d packets will saturate L2 cache of %d bytes\n",
	  vlen,
	  L2_CACHE);
  
  //
  // No IPC is required between children
  // but we want the children to receive the Ctrl+C and clean themselves up
  // before the parent goes away.
  //
  pid = 1;
  if( ! (kids = (pid_t *)malloc(sizeof(pid_t) * children))) {
    perror("malloc()");
    exit(EXIT_FAILURE);
  }

  // Make the filename?
  if(tmp1[0] == 0x0) {
    secs = time(NULL);
    localtime_r(&secs, &lt);
    strftime(tmp1, 1024, "%Y-%m-%d_%H-%M-%S", &lt);
  }

  fprintf(stderr, "packette (parent): Using output prefix '%s'\n", tmp1);

  // Allocated shared memory for performance statistics
  if(! (scratchpad = mmap(NULL,
			  children*sizeof(unsigned long)*2,
			  PROT_READ | PROT_WRITE,
			  MAP_SHARED | MAP_ANONYMOUS,
			  -1,
			  0))) {

    perror("mmap()");
    exit(EXIT_FAILURE);
  }
  
  fprintf(stderr, "packette (parent): Created shared memory scratchpad for performance reporting.\n");
  
  ////////////////////// SPAWNING ////////////////////
  
  // Loop exits when:
  //    pid == 0 (i.e. you're a child)
  //           OR
  //    children == 0 (i.e. you've reached the end of your reproductive lifecycle)
  // Implemented as a negation.
  //
  fprintf(stderr, "packette (parent): Spawning %d children...\n", children);
  
  k = children;
  while(pid && k) {
    pid = fork();
    if(pid)
      kids[--k] = pid;
  }
  
  //////////////////////// FORKED ////////////////////
  
  if(!pid) {
    ////////////////// CHILD ///////////////////

    // What is our purpose?
    pid = getpid();

    // Pin ourselves to a separate processor
    CPU_ZERO(&mask);
    CPU_SET(k-1, &mask);
    if(sched_setaffinity(0, sizeof(mask), &mask)) {
      perror("sched_setaffinity()");
      fprintf(stderr, "WARNING (PID %d): Unable to pin to CPU %d. (Too many threads?)\n",
	      pid,
	      k-1);
    }
    else
      fprintf(stderr, "packette (PID %d): Pinned self to CPU %d.\n",
	      pid,
	      k-1);

    // Install signal handler so we cleanly flush packets
    // From GNU docs:
    //  https://www.gnu.org/software/libc/manual/html_node/Sigaction-Function-Example.html
    new_action.sa_handler = &flagInterrupt;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    ///////////////// INITIALIZATION ///////////////
    
    // Seed the random number generator with ... a better random number
    // RECYCLE: FILE *orphan_file (from reception), opt (from argument parsing)
    orphan_file = fopen("/dev/urandom", "rb");

    // TIL sizeof can take symbols!
    fread(&opt, sizeof(opt), 1, orphan_file);

    // Seed and close.
    srand(opt);
    fprintf(stderr, "packette (parent): Random number generator seeded with /dev/urandom\n");
    fclose(orphan_file);

    // Reset the pointer.
    orphan_file = 0x0;
    
    // Set the first expected sequence number to 0
    prev_seqnum = 0;
    
    ////////////////// STREAMS //////////////////
    
    // Open streams for output
    if(!ordered_file) {
      
      sprintf(tmp2, "rawdata/%s_%s_%d.ordered", tmp1, addr_str, port + k - 1);
      if( ! (ordered_file = fopen(tmp2, "wb"))) {
	perror("fopen()");
	exit(EXIT_FAILURE);
      }
    }
    
    sprintf(tmp2, "rawdata/%s_%s_%d.orphans", tmp1, addr_str, port + k - 1);
    
    // Open streams for output
    if( ! (orphan_file = fopen(tmp2, "wb"))) {
      perror("fopen()");
      exit(EXIT_FAILURE);
    }
    
    ///////////////////// SOCKET ////////////////////
    
    // Get ready to receive multiple messages on a socket!
    // Code adapted from: man 2 recvmmsg, EXAMPLE

    // Get a socket
    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd == -1) {
      perror("socket()");
      exit(EXIT_FAILURE);
    }

    // Set the port with proper endianness
    sa.sin_port = htons(port + k - 1);
    sa.sin_family = AF_INET;

    // Why does this always have an explicit cast in the examples?
    // I guess so the code block is self-explanatory...
    if (bind(sockfd, &sa, sizeof(sa)) == -1) {
      perror("bind()");
      exit(EXIT_FAILURE);
    }

    // Report success
    fprintf(stderr,
	    "packette (PID %d): Listening at %s:%d...\n",
	    pid,
	    addr_str,
	    port + k - 1);
        
    // Now need to allocate the message structures
    retval =
      (msgs = (struct mmsghdr *)malloc( sizeof(struct mmsghdr) * vlen)) &&
      (iovecs = (struct iovec *)malloc( sizeof(struct iovec) * vlen)) &&
      (buf = malloc(BUFSIZE * vlen));
    
    if (!retval) {
      perror("malloc()");
      exit(EXIT_FAILURE);
    }
    
    // Report success.
    fprintf(stderr,
	    "packette (PID %d): Allocated %d bytes for direct socket transfer of %d packets.\n",
	    pid,
	    BUFSIZE * vlen,
	    vlen);
    
    // Now we do the magic.
    // We read in directly to payload buffers, which are offsets into a contiguous block
    memset(msgs, 0, sizeof(struct mmsghdr) * vlen);
    
    // Set this up to directly transfer payloads
    for (i = 0; i < vlen; i++) {
      iovecs[i].iov_base         = buf + i*(BUFSIZE);         // This should be a correctly operating pointer arithmetic...
      iovecs[i].iov_len          = BUFSIZE;
      msgs[i].msg_hdr.msg_iov    = &iovecs[i];
      msgs[i].msg_hdr.msg_iovlen = 1;
    }

    ///////////////////// PERFORMANCE REPORTING ///////////////////

    // Set up volatile pointers into the shared memory
    packets_processed_ptr = (unsigned long *)scratchpad + 2*(k-1);
    bytes_processed_ptr = (unsigned long *)scratchpad + 2*(k-1)+1;

    *packets_processed_ptr = 0;
    *bytes_processed_ptr = 0;
    
    timeout.tv_sec = TIMEOUT;
    timeout.tv_nsec = 0;

    // Now pull packets in bulk
    // Pull as many as will fit in L2 cache on your platform
    while(1) {

      // Try to grab at most vlen packets, timing out after TIMEOUT
      retval = recvmmsg(sockfd, msgs, vlen, 0, &timeout);

#undef DEBUG
#ifdef DEBUG
      fprintf(stderr,
	      "packette (PID %d): Received %d packets.\n",
	      pid,
	      retval);
#endif
      
      // Process only the packets received
      if (retval > 0) {

	// XXX? Maybe we don't need to use the __atomic_X operations?
	//
	// Since these are flagged as volatile, this could be super slow
	// since flagged as volatile... (lots of cache misses)
	// Guess we'll find out... this might be why Solarflare's code
	// ran so poorly?

	
	stash = prev_event_num;
	
	*bytes_processed_ptr += (*process_packets_fptr)(buf, msgs, retval, ordered_file, orphan_file, &prev_seqnum, &prev_event_num);
	*packets_processed_ptr += retval;

	// Keep track of packets received
	// (check is never evaluated if count = 0)
	if(count && (prev_event_num > stash)) {
	  if(!(--count - 1)) {
	    fprintf(stderr,
		    "packette (PID %d): Reached event limit.  Finishing up...\n");
	    break;
	  }
	}


	
      }
      else {

	// If there was trouble, see if there was an interrupt
	if (retval == -1) {
	  perror("recvmmsg()");

	  // Check for a Ctrl+C interrupt
	  // Only check the volatile if the socket read got disrupted
	  if(interrupt_flag) {
	    
	    // Someone pressed Ctrl+C
	    fprintf(stderr,
		    "packette (PID %d): Received SIGINT, finishing up...\n",
		    pid);
	    break;
	  }
	}
      }
    }

    // Close the file descriptors
    fclose(ordered_file);
    fclose(orphan_file);
    
    // Free the scatter-gather buffers
    free(buf);

    // Free the message structures themselves
    free(iovecs);
    free(msgs);

    fprintf(stderr,
	    "packette (PID %d): Done.\n",
	    pid);
  }
  else {
    ////////////////// PARENT //////////////////

    // Capture SIGINT
    new_action.sa_handler = &flagInterrupt;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    // Allocate and initialize some local accounting for da kids
    if(!(previous_processed = (unsigned long *)malloc(sizeof(unsigned long)*children*2))) {
      perror("malloc()");
      exit(EXIT_FAILURE);
    }

    // Zero it out
    memset(previous_processed, 0x0, sizeof(unsigned long)*children*2);

    //////////////////////////// PERFORMANCE REPORTING /////////////////////

    if(ordered_file != stdout) {
	 
      // Enter ncurses mode
      initscr();

      // Print out a message and table header
      mvprintw(0, 0, packette_logo);
      mvprintw(9, 1, "PID");
      mvprintw(9, 1+6, "| Instantaneous rate");
      mvprintw(9, 1+6+33, "| Cumulative data");
      mvprintw(10, 0, "-----------------------------------------------------------------");
    }
    
#define REFRESH_PERIOD 100000
    while(1) {

      // Reset timeout
      if(ordered_file != stdout) {
	parent_timeout.tv_sec = 0;
      	parent_timeout.tv_usec = REFRESH_PERIOD;
      }
      else {
	parent_timeout.tv_sec = 1;
	parent_timeout.tv_usec = 0;
      }
	
      // Sit in timeout for exactly TIMEOUT 
      while(1) {

	// select() on stdin and dgaf about keystrokes
	select(0, NULL, NULL, NULL, &parent_timeout);
	if(parent_timeout.tv_usec == 0)
	  break;
      }

      // Check for Ctrl+C
      if(interrupt_flag) {
	fprintf(stderr,
	    "packette (parent): Received SIGINT, waiting for children to finish...\n");
	break;
      }

      // Check for the all children finished condition
      // (The errno check is required in case the parent races
      //  and the child process is not completely set up yet)
      k = children;
      retval = 1;
      while(retval && k--)
	retval &= !errno & !(kids[k] - waitpid(kids[k], NULL, WNOHANG));

      if(retval)
	break;
      
      // Reset the output buffer position for sprintf
      output[0] = 0;

      // Reset the running totals
      total_kpps = 0.0;
      total_MBps = 0.0;
      total_Mp = 0.0;
      total_MB = 0.0;

      for(k = 0; k < children; ++k) {

	// Make some volatile pointers into shared memory
	packets_processed_ptr = (unsigned long *)scratchpad + 2*k;
	bytes_processed_ptr = (unsigned long *)scratchpad + 2*k + 1;

	// Pull values from the volatile locations once
	packets_processed = *packets_processed_ptr;
	bytes_processed = *bytes_processed_ptr;
	
	// XXX Clearly not safe
	// packets always 33 wide
	sprintf(output,
		"%s%6.d | %9.3f kpps (%9.3fMBps) | %7.3f Mp (%7.3fMB)\n",
		output,
		kids[k],
		1000.0*(packets_processed - previous_processed[2*k])/REFRESH_PERIOD,
		1.0*(bytes_processed - previous_processed[2*k + 1])/REFRESH_PERIOD,
		packets_processed/1e6,
		bytes_processed/1e6);

	// Add totals
	total_kpps += 1000.0*(packets_processed - previous_processed[2*k])/REFRESH_PERIOD;
	total_MBps += 1.0*(bytes_processed - previous_processed[2*k + 1])/REFRESH_PERIOD;
	
	total_Mp += packets_processed/1.0e6;
	total_MB += bytes_processed/1.0e6;
	
	// Store for computation of instantaneous performances
	previous_processed[2*k] = packets_processed;
	previous_processed[2*k + 1] = bytes_processed;
      }
      
      // Add in the totals
      sprintf(output,
	      "%s-----------------------------------------------------------------\n", output);

      sprintf(output,
	      "%s Total | %9.3f kpps (%9.3fMBps) | %7.3f Mp (%7.3fMB)\n\n",
	      output,
	      total_kpps,
	      total_MBps,
	      total_Mp,
	      total_MB);

      // ncurses output?
      if(ordered_file != stdout) {
	mvprintw(11,0,output);
	mvprintw(15,0,"Press Ctrl+C when you've had your fill...");
	if(count > 0) {
	  sprintf(output, "...otherwise accumulating %d events per child", count-1);
	  mvprintw(16,0,output);
	}
	
	refresh();
      }
   }

    // Close ncurses?
    if(ordered_file != stdout)
      endwin();
    
    // Wait for the children to finish up
    k = children;
    while(k--) {
      waitpid(kids[k], &retval, 0);
      fprintf(stderr,
	      "packette (parent): child-%d (PID %d) has completed\n",
	      k,
	      kids[k]);
    }

    // Unmap the shared memory
    if(munmap(scratchpad, children*sizeof(unsigned long)*2)) {

      perror("munmap()");
      exit(EXIT_FAILURE);
    }

    fprintf(stderr, "packette (parent): Deallocated shared memory scratchpad.\n");
    
    // Unnecessary Cleanup
    free(previous_processed);
    free(kids);
    exit(0);
  }
  
  // Even though this will get torn down on process completion,
  // come correct.
  //  cleanup();
}   
