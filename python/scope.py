# !/usr/bin/env python

# Displays a scope-like view of the CCD output waveform, matched with the clock states of the sequencer function
# used to acquire it.
#
# Changelog
# 20161205: C. Juramy, initialized from LPNHE bench code.
# 20170316: added more options for plots
# 20170320: added management for file format: raw or fits
#
#
# Syntax as main:
# python scope.py [dsi-scan.fits] [tm-scan.fits] [sequencer-file.seq] [Channel] <[Main *or* function used for readout]>
# Example:
# python scope.py dsi-scan.fits tm-scan.fits seq-newflush.txt Segment00
# With LPNHE file formats:
# python scope.py dsi_scan_0x0020161027151605.fits tm_scan_0x0020161027151628.fits test-multiflush.txt chan_09
#
# Syntax in a script:
# import scope
# scope.combined_scope_display("dsi-scan.fits", "tm-scan.fits", "seq-newflush.txt", "Segment00", "Bias")

import sys
import os.path
import pyfits
import numpy as np
from matplotlib import pyplot as plt

# add sequencer reading method
import rebtxt

# global for path to sequencer file
seqpath = "/Users/nayman/Documents/REB/TS8/sequencer-files"


def find_transition_index(states):
    """
    Finds the indexes of values changes in the list. Returns the first one.
    Obviously not meant for floats.
    :ptype states: np.array
    :rtype: np.array
    """

    return np.nonzero(states[1:] - states[:-1])[0] + 1


def set_legend_outside(ax):
    """
    Operations to put a matplotlib legend outside the plot area.
    :return:
    """
    box = ax.get_position()
    ax.set_position([box.x0, box.y0, box.width * 0.8, box.height])
    plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.)


def get_scandata_fromfile(inputfile, datadir='', selectchannels=None):
    """
    Reads data from the file, sets it straight if raw values, returns 3D array of (scan-)image data.
    We will look at file extension to guess what it it and how it is organized.
    :param selectchannels: which REB channel we want to include (numbered 0-15, 0-47 if full REB file). All if None.
    :param datadir: optional, directory where data is stored
    :param inputfile: the file where image data is stored. Needs full path if datadir is not provided.
    :return:
    """
    if os.path.splitext(inputfile)[1] in [".fits", ".fz"]:
        if selectchannels is None:
            displayamps = range(16)
        else:
            displayamps = selectchannels

        hdulist = pyfits.open(os.path.join(datadir, inputfile))
        imgdata = []
        for i in displayamps:
            imgdata.append(hdulist[i + 1].data)
            #print hdulist[i+1].data.shape
        hdulist.close()
        del hdulist  # clean-up

        chandata = np.stack(imgdata)

    else:
        nchannels = 48
        if selectchannels is None:
            displayamps = range(nchannels)
        else:
            displayamps = selectchannels

        dt = np.dtype('i4')
        buff = np.fromfile(os.path.join(datadir, inputfile), dtype=dt)
        # for 18-bit data:
        # negative numbers are translated, sign is inverted on all data, also make all values positive
        # 0 -> 1FFFF, 1FFFF -> 0, 20000 -> 3FFFF, 3FFFF -> 20000
        # this works by XORing the lowest 17 bits
        rawdata = np.bitwise_xor(buff, 0x1FFFF)
        # reshape by channel
        length = rawdata.shape[0] / nchannels
        # temporary fix for missing last pixel
        rawdata = rawdata[:256 * (length/256) * nchannels]
        rawdata = rawdata.reshape(length/256, 256, nchannels)  # assumes this is a scan image

        chandata = np.transpose(rawdata[:, :, displayamps], (2, 0, 1))  # puts the channel as first axis
        # TODO: match the order from the fits file

    #print chandata.shape
    return chandata


def get_rootfile(filename):
    rootname = ''
    # remove path, extension, and up to first '_'
    try:
        rootname = os.path.splitext(os.path.basename(filename))[0]
        rootname = rootname.split('_',1)[1]
    except:
        pass
    return rootname


def plot_scan_states(ax, seq, readfunction, offset=0, extend=1, marktransitions=True):
    """
    Auxiliary function: handles plotting the sequencer states on the given matplotlib ax.
    :param ax: Matplotlib axis
    :param seq: sequencer object
    :param readfunction: name of sequencer function to be plotted
    :param offset: offset between beginning of sequencer function and ADC trigger
    :param extend: if the function lasts longer than 2560 ns
    :param marktransitions: if the vertical grid marks the clock transitions instead of regular ticks
    :return:
    """
    funcscope = seq.functions_desc[readfunction]['function']  # function object
    clocklist = seq.functions_desc[readfunction]['clocks']  # names of active clocks

    ax.set_ylabel('Sequencer states')
    ax.set_ylim((0, len(clocklist)))
    ax.set_yticks(np.arange(len(clocklist)))
    ax.set_yticklabels(clocklist)

    # creates waveform for each clock with matching timing
    clocktransitions = np.array([0, 255 + 256 * (extend - 1)])  # add boundaries of scan
    for i, clock in enumerate(clocklist):
        clockline = seq.channels[clock]
        states = funcscope.scope(clockline)
        scanstates = np.tile(np.array(states), 3 * extend)[offset:offset + 256 * extend]
        #print find_transition_index(scanstates)
        clocktransitions = np.concatenate((clocktransitions, find_transition_index(scanstates)))
        ax.plot(scanstates * 0.8 + i, drawstyle='steps-post')

    # setups X-axis
    ax.set_xlabel('Time increment (10 ns)')
    if marktransitions:
        # new option
        clocktransitions = np.unique(clocktransitions)
        #print clocktransitions
        ax.set_xticks(np.array(clocktransitions))
    else:
        # old version: regular ticks
        ax.set_xticks(np.arange(0, 256 * extend, 256))

    ax.grid(axis='both')


def sequencer_display(seqfile, readout='Acquisition', trigname='TRG'):
    """
    Display sequencer states only.
    Needs to be given the name of the main used.
    Will detect automatically the function used and the offset of the ADC.
    :param seqfile: sequencer file, needs full path from seqpath global variable.
    :param readout: function or program used during fits file acquisition
    :param trigname: name of the ADC trigger clock in the sequencer file
    """

    # gets sequencer object
    seq = rebtxt.Sequencer.fromtxtfile(os.path.join(seqpath, seqfile), verbose=False)

    # finds the function used for readout if given the Main
    if readout in seq.functions_desc:
        readfunction = readout
    else:
        readfunction = seq.find_function_withclock(readout, 'TRG')


    # find offset between start of function and trigger of ADC
    clockline = seq.channels['TRG']
    funcscope = seq.functions_desc[readfunction]['function']  # function object
    offset = funcscope.scope(clockline).index(1)

    fig, ax = plt.subplots(figsize=(13, 8))
    plot_scan_states(ax, seq, readfunction, offset)
    plt.savefig(os.path.join(seqpath, "sequencerscope.png"))
    plt.show()


def scan_scope_display(dsifile, tmfile, displayamps=range(16), append=False, datadir=''):
    """
    Separate display of scans, to call it from the script or to do it offline.
    :param idsi: fits file with scan data in normal DSI mode (none is accepted)
    :param itm: fits file with scan data in Transparent Mode (none is accepted but not recommended)
    :param displayamps: list of amplifiers to display
    :param append: if all amplifiers should be displayed stitched together or superimposed (if False)
    :param datadir: path to image files (optional), also path for output PNG
    """
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.grid(True)

    dataname = ''
    try:
        dsihdu = get_scandata_fromfile(dsifile, datadir, selectchannels=displayamps)
        dataname = os.path.splitext(os.path.basename(dsifile))[0]
    except:
        dsihdu = None
    try:
        tmhdu = get_scandata_fromfile(tmfile, datadir, selectchannels=displayamps)
        dataname = os.path.splitext(os.path.basename(tmfile))[0]
    except:
        tmhdu = None

    if append:
        # skips first scan line
        if dsihdu is not None:
            dsiscope = dsihdu[:, 1:, :].mean(axis=1).flatten()
            ax.plot(dsiscope)
        if tmhdu is not None:
            tmscope = tmhdu[:, 1:, :].mean(axis=1).flatten()
            ax.plot(tmscope)

        ax.set_xlabel('Scanned channel')
        ax.set_xticks(np.arange(0, 256 * len(displayamps), 256), displayamps)

    else:
        # separate line for each scan
        # with appropriate color schemes
        color_idx = [plt.cm.jet(i) for i in np.linspace(0, 1, len(displayamps))]

        for i, c in enumerate(displayamps):
            if dsihdu is not None:
                dsiscope = dsihdu[i].mean(axis=0)
                np.clip(dsiscope, 0, dsiscope[1:].max(), out=dsiscope)
                ax.plot(dsiscope, label='DSI-C%d' % c, color=color_idx[i])
            if tmhdu is not None:
                tmscope = tmhdu[i].mean(axis=0)
                np.clip(tmscope, 0, tmscope[1:].max(), out=tmscope)
                ax.plot(tmscope, label='TM-C%d' % c, color=color_idx[i])

        ax.set_xlim(0, 255)
        ax.set_xticks(np.arange(0, 256, 32))
        ax.set_xlabel('Time increment (10 ns)')
        ax.set_ylabel('Scan (ADU)')
        set_legend_outside(ax)

    plt.title(dataname)
    plt.savefig(os.path.join(datadir, "scanplot-%s.png" % dataname))
    plt.show()


def combined_scope_display(dsifile, tmfile, seqfile, c, readout='ReadPixel', datadir='', loc='', display=True):
    """
    Display scan scope for a channel along with sequencer states.
    Can be given the name of the main used (will detect automatically the function used and the offset of the ADC),
    or the name of the readout function. What is hardcoded here is the name of the ADC trigger ('TRG').
    Averages over all scan lines that are supposed to be within the detector physically.
    :param datadir: path to image files (optional), also path for output PNG
    :param dsifile: fits or raw file with scan data in normal DSI mode (None is accepted)
    :param tmfile: fits or raw file with scan data in Transparent Mode (None is accepted)
    :param seqfile: sequencer file, needs full path
    :param c: extension name
    :param readout: function or program used during fits file acquisition
    :param loc: a string to give additionnal information in the plot title, like the CCD type or location
    """

    # image extensions are labeled as 'Segment00' in CCS
    # they are in extensions 1 to 16
    # skip first line (assuming we may have only 4)
    dataname = ''
    try:
        dsiscope = get_scandata_fromfile(dsifile, datadir, selectchannels=[c])
        dsiscope = dsiscope[0].mean(axis=0)  # 3D array, select single channel
        dataname = get_rootfile(dsifile)
    except:
        dsiscope = None
    try:
        tmscope = get_scandata_fromfile(tmfile, datadir, selectchannels=[c])
        tmscope = tmscope[0].mean(axis=0)  # same
        dataname = get_rootfile(tmfile)
    except:
        tmscope = None

    # gets sequencer object
    seq = rebtxt.Sequencer.fromtxtfile(os.path.join(seqpath, seqfile), verbose=False)

    # finds the function used for readout if given the Main
    if readout in seq.functions_desc:
        readfunction = readout
    else:
        readfunction = seq.find_function_withclock(readout, 'TRG')

    funcscope = seq.functions_desc[readfunction]['function']  # function object

    fig, ax1 = plt.subplots(figsize=(13, 8))
    ax1.set_xlabel('Time increment (10 ns)')
    # ax1.set_xlim(0,255)
    ax1.set_xticks(np.arange(0, 256, 32))
    if dsiscope is not None:
        # cuts first point if anomalous (because trigger occurs before pixel transfer)
        np.clip(dsiscope, 0, dsiscope[1:].max(), out=dsiscope)
        ax1.plot(dsiscope, label='DSI')
    if tmscope is not None:
        # cuts first point if anomalous (because trigger occurs before pixel transfer)
        np.clip(tmscope, 0, tmscope[1:].max(), out=tmscope)
        ax1.plot(tmscope, label='TM')
    ax1.set_ylabel('Scan (ADU)')
    ax1.grid(axis='x')

    ax2 = ax1.twinx()
    ax2.grid(True)

    # find offset between start of function and trigger of ADC
    clockline = seq.channels['TRG']
    offset = funcscope.scope(clockline).index(1)

    plot_scan_states(ax2, seq, readfunction, offset)

    readfile = os.path.basename(seqfile)
    plt.title("%s in %s for %s-channel %02d" % (readfunction, readfile, loc, c))
    plt.savefig(os.path.join(datadir, "combinedscope-%s-%s-%02d.png" % (dataname, loc, c)))

    if display:
        plt.show()


def compare_scope_display(scanlist, labellist, datadir='', displayamps=range(16)):
    """
    Displays several scans on the same plot for each (selected) channel of the CCD.
    :return:
    """

    dataname = os.path.splitext(os.path.basename(scanlist[0]))[0]
    # number of plots to do
    ndisplay = len(scanlist)

    alltmhdu = []
    for tmfile in scanlist:
        try:
            # loads up all data in one array
            alltmhdu.append(get_scandata_fromfile(tmfile, datadir, selectchannels=displayamps))
        except:
            ndisplay -= 1
            continue
    print "Found %d scan files to display" % ndisplay
    # plot
    fig, axes = plt.subplots(nrows=(len(displayamps) + 3)/4, ncols=4, figsize=(10, 10))

    # color scheme
    color_idx = [plt.cm.jet(i) for i in np.linspace(0, 1, ndisplay)]

    for c in range(len(displayamps)):  # channels to display
        # subplot
        ax = axes[c / 4, c % 4]

        for i in range(ndisplay):  # scan files for a channel
            tmhdu = alltmhdu[i]
            tmscope = tmhdu[c].mean(axis=0)
            # first point is often invalid due to trigger position
            np.clip(tmscope, 0, tmscope[1:].max(), out=tmscope)
            ax.plot(tmscope, label=labellist[i], color=color_idx[i])

        ax.set_xlim(0, 255)
        ax.set_xticks(np.arange(0, 256, 32))
        #ax.set_xlabel('Time increment (10 ns)')
        #ax.set_ylabel('Scan (ADU)')
        ax.grid(True)
        #set_legend_outside(ax)

    plt.title(dataname)
    plt.savefig(os.path.join(datadir, "scancompare-%s.png" % dataname))
    plt.show()


if __name__ == '__main__':
    idsi = sys.argv[1]
    itm = sys.argv[2]
    seqfile = sys.argv[3]
    c = sys.argv[4]
    if len(sys.argv) > 5:
        readout = sys.argv[5]
    else:
        readout = 'ReadPixel'

    combined_scope_display(idsi, itm, seqfile, c, readout)
