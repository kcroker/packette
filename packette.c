#define _GNU_SOURCE

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

// Time
#include <time.h>

// Local stuff
#include "packette.h"

///////////////////////////// GLOBALS /////////////////////////

// Note that things are unsigned long because we want to avoid implicit casts
// during computation.
void (*process_packets_fptr)(void *buf, int vlen);
unsigned long fragments_per_channel;
unsigned long current_evt_seqnum;

unsigned long *emptyBlock;

// This is used to signal that we should cleanup
volatile sig_atomic_t interrupt_flag = 0;

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
// Everytime we push to the stream
//

void process_packets(void *buf, int vlen) { 

  //
  // The essential points to reconstruction are that:
  // 1) the sequence number increases monotonically from 0.
  // 2) roi_width tells us how much data we have
  // 3) channel mask lets us know how many payloads to expect
  // 4) event number lets us know if we've changed events
  //

  //
  // The simplest implementation is to write a no-data 
  // block of the correct size.  Then fill it in.
  //
  // This can later be optimized to either.  Fuck it.
  // Do it the fast way.  From the start.
  //

  struct packette_raw *ptr;
  unsigned long prev_seqnum;
  unsigned long delta;
  unsigned short prev_eventnum;
  unsigned char activeChannels;
  unsigned char channelMap;

  while(vlen--) {

    // Get the first one, casting it so we can extract the fields
    ptr = (struct packette_raw *)buf;

    // How many packets did we drop/lose?
    delta = ptr->header.seqnum - prev_seqnum;
    
    // Are we on the same event?
    if(ptr->header.event.eventnum == prev_eventnum) {

    }
    else {

      // Recompute the number of active channels
      
    }
    
    // Stash these for the next packet
    prev_seqnum = ptr->header.seqnum;
    prev_eventnum = ptr->header.event.eventnum;

    // Get the next one (the buffer is contiguous)
    buf += BUFSIZE;
  }

    
  
  // 
  //
  // There are two situations to consider
  //

    // This lets us fill in gaps in the outgoing stream
  //
  // Currently, this only supports one ROI per channel per
  // hit
  //
  // I do need an event number
  //
  
  
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
} 

//
// Perform initialization based on the first packet received
//
void preprocess_first_packet(void *p, int vlen) {

  unsigned long mask;
  unsigned char i;
  
  // Set the process function to subsequent packets
  // (this way we avoid an if every time to see if we are first)
  process_packets_fptr = &process_packets;

  // Process this first packet!
  (*process_packets_fptr)(p, vlen);
}

//
// Called when the child receives SIGINT
//
void flushChild(int signum) {

  // This is a special volatile signal-safe integer type:
  //  https://wiki.sei.cmu.edu/confluence/display/c/SIG31-C.+Do+not+access+shared+objects+in+signal+handlers
  interrupt_flag = 1;
}

#define L2_CACHE 256000
#define TIMEOUT 1

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

  // Argument parsing stuff
  int flags, opt;
  int nsecs, tfnd;
  unsigned short port;
  unsigned long roi_width;
  unsigned long max_packets;
  char *addr_str;

  // Signal handling stuff
  struct sigaction new_action, old_action;

  // Files and data output stuff
  FILE *ordered_file;            // Stage I reconstruction (ordered and stripped) output
  FILE *orphan_file;               // Stage II reconstruction (unordered, raw) output
  struct tm lt;            // For holding time stuff
  time_t secs;
  char tmp1[1024], tmp2[1024];
  
  // lol basic shit in C is annoying.
  // Default values
  port = 1338;
  roi_width = 1024;
  children = 1;
  addr_str = 0x0;
  max_packets = ~0;
  
  /////////////////// ARGUMENT PARSING //////////////////
  
  while ((opt = getopt(argc, argv, "t:p:w:m:")) != -1) {
    switch (opt) {
    case 't':
      children = atoi(optarg);
      break;
    case 'p':
      port = atoi(optarg);
      break;
    case 'w':
      roi_width = atoi(optarg);
      break;
    case 'm':
      max_packets = strtoul(optarg, NULL, 10);
      break;
    default: /* '?' */
      fprintf(stderr, "Usage: %s [-t threads] [-p base UDP port] [-w samples per ROI] [-m max packets per thread] BIND_ADDRESS\n",
	      argv[0]);
      exit(EXIT_FAILURE);
    }
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
	  "Packette (parent): %d children will bind at %s, starting from port %d\n",
	  children,
	  argv[optind],
	  port);

  ///////////////// PARSING COMPLETE ///////////////////
  
  // Set the initial packet processing pointer to the preprocessor
  process_packets_fptr = &preprocess_first_packet;

  // Now compute the optimal vlen via truncated idiv
  vlen = L2_CACHE / BUFSIZE;
  fprintf(stderr,
	  "Packette (parent): Determined %d packets will saturate L2 cache of %d bytes\n",
	  vlen,
	  L2_CACHE);
  
  //
  // No IPC is required between children
  // but we want the parent to receive the Ctrl+C and clean up the children.
  //
  pid = 1;
  if( ! (kids = (pid_t *)malloc(sizeof(pid_t) * children))) {
    perror("malloc()");
    exit(EXIT_FAILURE);
  }
  
  ////////////////////// SPAWNING ////////////////////
  
  // Loop exits when:
  //    pid == 0 (i.e. you're a child)
  //           OR
  //    children == 0 (i.e. you've reached the end of your reproductive lifecycle)
  // Implemented as a negation.
  //
  fprintf(stderr, "Packette (parent): Spawning %d children...\n", children);
  
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

    // Install signal handler so we cleanly flush packets
    // From GNU docs:
    //  https://www.gnu.org/software/libc/manual/html_node/Sigaction-Function-Example.html
    new_action.sa_handler = &flushChild;
    sigemptyset (&new_action.sa_mask);
    new_action.sa_flags = 0;

    sigaction(SIGINT, NULL, &old_action);
    if (old_action.sa_handler != SIG_IGN)
      sigaction(SIGINT, &new_action, NULL);

    ////////////////// STREAMS //////////////////
    
    // Make the filename
    //
    // (YIKES We had to use the _r call here, due to "thread safety"
    //  I guess threads is more than just pthreads, but its also processes!)
    secs = time(NULL);
    localtime_r(&secs, &lt);
    
    strftime(tmp1, 1024, "%Y-%m-%d_%H-%M-%S", &lt);
    sprintf(tmp2, "%s_%s_%d.ordered", tmp1, addr_str, port);
    	    
    // Open streams for output
    if( ! (ordered_file = fopen(tmp2, "wb"))) {
      perror("fopen()");
      exit(EXIT_FAILURE);
    }

    sprintf(tmp2, "%s_%s_%d.orphans", tmp1, addr_str, port);
    
    // Open streams for output
    if( ! (orphan_file = fopen(tmp2, "wb"))) {
      perror("fopen()");
      exit(EXIT_FAILURE);
    }
    
    // Get ready to receive multiple messages on a socket!
    // Code adapted from: man 2 recvmmsg, EXAMPLE

    // Get a socket
    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd == -1) {
      perror("socket()");
      exit(EXIT_FAILURE);
    }

    // Get the given IP and port from strings
    // Set the port (truncate, base 10, ignore bs characters)
    // XXX Don't check for errors ;)
    sa.sin_port = port + k - 1;
    sa.sin_family = AF_INET;

    // Why does this always have an explicit cast in the examples?
    // I guess so the code block is self-explanatory...
    if (bind(sockfd, &sa, sizeof(sa)) == -1) {
      perror("bind()");
      exit(EXIT_FAILURE);
    }

    // Report success
    fprintf(stderr,
	    "Packette (PID %d): Listening at %s:%d...\n",
	    pid,
	    addr_str,
	    sa.sin_port);
        
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
	    "Packette (PID %d): Allocated %d bytes for direct socket transfer of %d packets.\n",
	    pid,
	    BUFSIZE * vlen,
	    vlen);
    
    // Now we do the magic.
    // We read in directly to payload buffers
    memset(msgs, 0, sizeof(struct mmsghdr) * vlen);
    
    // Set this up to directly transfer payloads
    for (i = 0; i < vlen; i++) {
      iovecs[i].iov_base         = buf + i*(BUFSIZE);         // This should be a correctly operating pointer arithmetic...
      iovecs[i].iov_len          = BUFSIZE;
      msgs[i].msg_hdr.msg_iov    = &iovecs[i];
      msgs[i].msg_hdr.msg_iovlen = 1;
    }

    timeout.tv_sec = TIMEOUT;
    timeout.tv_nsec = 0;

    // Now pull packets in bulk
    // Pull as many as will fit in L2 cache on your platform
    while(1) {

      retval = recvmmsg(sockfd, msgs, vlen, 0, &timeout);
      if (retval == -1)
    	perror("recvmmsg()");

      // Process the packets
      (*process_packets_fptr)(buf, vlen);
	
      // Check for a Ctrl+C interrupt
      if(interrupt_flag) {

	// Someone pressed Ctrl+C
	fprintf(stderr,
		"Packette (PID %d): Received SIGINT, finishing up...\n",
		pid);
	break;
      }
      
      /* printf("%d messages received\n", retval); */
      /* for (i = 0; i < retval; i++) { */
      /* 	bufs[i][msgs[i].msg_len] = 0; */
      /* 	printf("%d %s", i+1, bufs[i]); */
      /* } */
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
	    "Packette (PID %d): Done.\n",
	    pid);
  }
  else {
    ////////////////// PARENT //////////////////

    // Block SIGINT
    sigemptyset (&new_action.sa_mask);
    new_action.sa_handler = SIG_IGN;
    sigaction(SIGINT, &new_action, NULL);

    fprintf(stderr,
	    "Packette (parent): waiting for children to finish...\n");
    
	    
    k = children;
    while(k--) {
      waitpid(kids[k], &retval, 0);
      fprintf(stderr,
	      "Packette (parent): child-%d (PID %d) has completed\n",
	      k,
	      kids[k]);
    }
    
    exit(0);
  }
  
  // Even though this will get torn down on process completion,
  // come correct.
  free(kids);
  //  cleanup();
}   
