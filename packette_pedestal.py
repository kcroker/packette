#
# Simple container object.
#
class pedestal(object):

    def __init__(self, means, rmss, counts):

        # Set up for pedestals
        self.mean = means
        self.rms = rmss
        self.counts = counts
