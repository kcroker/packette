#
# Simple container object.
#
# (I know.  Please don't ask me about this file)
#
class pedestal(object):

    def __init__(self, means, rmss, counts):

        # Set up for pedestals
        self.mean = means
        self.rms = rmss
        self.counts = counts

#import argparse
#import sys

# # do the merger
# if __name__ == 'main':

#     pedestals = sys.argv.split()

#     for p in pedestals:
#         data = 
