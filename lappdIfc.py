#!/usr/bin/python3

import sys
import os
import eevee 
import time
import numpy as np

# temporarily here
SW_VERSION      = 0x0000
FW_VERSION      = 0x0004
DEVICEDNA_L     = 0x0008
DEVICEDNA_H     = 0x0010
EFUSEVAL        = 0x0018
SCRATCH         = 0x0020
SYS_FREQ        = 0x0030
SRCMAC_LOW      = 0x0100   
SRCMAC_HIGH     = 0x0108   
SRCIP           = 0x0110   
EEVEE_CLOCK     = 0x0120   
DESTMAC_LOW     = 0x0200
DESTMAC_HIGH    = 0x0208
DESTIP          = 0x0210
# Source port is low u16, destination port is high u16          
NBIC_PORTS      = 0x0218

CMD             = 0x0320 # asserted for 1 clk cycle see description of bits below
ADCBUFNUMWORDS  = 0x0328 # number of DRS samples, if <=1024 then ROI mode else FULL
ADCDEBUG1       = 0x0330 # continuously registered ADC data for the channel number ADCDEBUGCHAN 
ADCBUFDEBUG     = 0x0338
ADCCLKDELAY     = 0x0340 # IDELAY 
ADCFRAMEDELAY_0 = 0x0348 # IDELAY
BITSLIP         = 0x0350 # manual bitslip ADC2 & ADC1
ADCWORDSWRITTEN = 0x0358 # obsolete TODO : remove
ADCDEBUGCHAN    = 0x0360 # channel to be read out via reg interface
BITSLIPCNT      = 0x0368
MODE            = 0x0370 # see bits disctiption below
DRSPLLLCK       = 0x0378 # PLL Lock states
ADCBUFCURADDR   = 0x0380 # current position in ADC buffer
STATUS          = 0x0388 # reserved, not filled at the moment
DRSREFCLKRATIO  = 0x0390 # REFCLK ratio
ADCFRAMEDEBUG   = 0x03A8 # not used anymore
ADCDATADELAY_0  = 0x0400 # IDELAY for ADC data lines (64 registers, i-th channel ADCDATADELAY_0 + i*4) 

ADCDELAYDEBUG   = 0x0500 # readback IDELAY delay values
DRSADCPHASE     = 0x0600 # 8ns tune of phase between ADC cov clock and SRCLK
NSAMPLEPACKET   = 0x0610 # maximum number of samples in the packet
DRSVALIDPHASE   = 0x0618 #   
DRSVALIDDELAY   = 0x0620 # delay drs valid to choose between oversampling samples  

EBDEBUG         = 0x0628 # debug                
DRSWAITSRIN     = 0x0630 # debug              
DRSWAITADDR     = 0x0638 # debug         
DRSWAITSTART    = 0x0640 # debug         
DRSWAITINIT     = 0x0648 # debug         
DRSSTOPSAMPLE_0 = 0x0650 # stop sample for chan 0 (for ith channel + 4*i)
ADCCHANMASK_0   = 0x0670 # mask of ADC channels to be sent 
NUDPPORTS       = 0x0678 # number of UDP ports for multiple ports mode 
ZEROTHRESH_0    = 0x0700 # thresholds for zero suppression
EXTTRGCNT       = 0x0800 # counter for external triggers



###################################
# Command register. 
# Bits are set for 1 clock cycle
################################### 
C_CMD_RESET_BIT     = 0 # reset signal (reset of internal regs to defaults is not implemented yet)
C_CMD_ADCCLEAR_BIT  = 1 # obsolete
C_CMD_ADCSTART_BIT  = 2 # obsolete
C_CMD_ADCTXTRG_BIT  = 3 # send TxTrig signal to ADCs
C_CMD_ADCRESET_BIT  = 4 # reset ADCs
C_CMD_ADCBTSLP_BIT  = 5 # obsolete
C_CMD_READREQ_BIT   = 6 # start DRS readout sequence
C_CMD_RUNRESET_BIT  = 7 # reset nun number and event building state machine
C_CMD_ADCRDRESET_BIT = 8 # reset nun number and event building state machine

##################################
# bits of MODE register
##################################
C_MODE_ADCBUF_WREN_BIT  = 0  # enable/disable ADC buffer which stores ADC samples
C_MODE_DRS_TRANS_BIT    = 1  # DRS4 transparence mode on/off
C_MODE_DRS_DENABLE_BIT  = 2  # DRS4 DENABLE signal
C_MODE_TCA_ENA_BIT      = 3  # enable time calibration oscillator
C_MODE_EB_FRDISABLE_BIT = 4  # disable packet fragmentation
C_MODE_EXTTRG_EN_BIT    = 5  # enable external trigger
C_MODE_DRS_REVRS_BIT    = 6  # reverse order of Drs stop samples 
C_MODE_CLKIN_TRG_BIT    = 7  # use CLKIN for the trigger input
C_MODE_PEDSUB_EN_BIT    = 8  # enable pedestal subtraction
C_MODE_ZERSUP_EN_BIT    = 9  # enable zero supression

# Old mapping
# ADDR_DAC_OFFSET = 0x1000
# ADDR_ADCSPI_OFFSET = 0x2000
# ADDR_ADCBUF_OFFSET = 0x3000 
# ADDR_DRSCFG_OFFSET = 0x4000
# ADDR_PEDMEM_OFFSET = 0x5000

ADDR_DAC_OFFSET    = (1 << 18) # DAC
ADDR_ADCSPI_OFFSET = (2 << 18) # ADC SPI control
ADDR_ADCBUF_OFFSET = (3 << 18) # ADC buffer reg interface
ADDR_DRSCFG_OFFSET = (4 << 18) # DRS4 registers
ADDR_PEDMEM_OFFSET = (8 << 18) # Pedestals memory


class lappdInterface :
    def __init__(self, ip = '10.0.6.193', udpsport = 8989):
        self.xx = 0
        # self.brd = eevee.board('10.0.6.212', udpsport = 7778)
        self.brd = eevee.board(ip, udpsport = udpsport) 
        self.peds = [0]*1024
        self.rmss = [0]*1024
        self.peds_roi = [0]*1024
        self.rmss_roi = [0]*1024
        self.AdcSampleOffset = 0
        self.TestPattern = [0xabc, 0x543]
        self.NCalSamples = 100
        self.drsrefclk = 51
        self.mask_adc1 = 1 << 15;
        self.mask_adc2 = 1 << 23;

        # dict for DAC voltages 'name' : [OUTN, VOLTS] 
        self.DACOUTS = {
            'BIAS'     : 0, 
            'ROFS'     : 1,
            'OOFS'     : 2,
            'CMOFS'    : 3,
            'TCAL_N1'  : 4,
            'TCAL_N2'  : 5,
            'TCAL_N3'  : 6,
            'TCAL_N4'  : 7
        }
        
    def RegRead(self, addr) :
        if type(addr) != int : addr = int(addr,0)
        val = self.brd.peeknow(addr)
        return val

    def RegWrite(self, addr, value) :
        if type(addr)  != int : addr  = int(addr,0)
        if type(value) != int : value = int(value,0)
        self.brd.pokenow(addr, value)
        return 0

    # modify only one bit of the register 
    def RegSetBit(self,addr, bit, bit_val) :
        if bit_val not in [0,1] :
            raise Exception("RegSetBit:: error:: val should be 0 or 1 ", file=sys.stderr)

        reg_val = self.brd.peeknow(addr)
        if bit_val == 1 :
            reg_val = reg_val | (1 << bit)
        else :
            reg_val = reg_val & (~(1 << bit))
        self.brd.pokenow(addr, reg_val)


    def SetAdcReg(self, nadc, reg, val):
        if type(reg) != int : reg = int(reg,0) # 8-bit addres space
        if type(val) != int : val = int(val,0)

        if reg < 0 or reg > 0xff :
            raise Exception('Wrong ADC register address : %d' % (reg))
        if val < 0 or val > 0xffff :
            raise Exception('Wrong ADC reg value : %d' % (val))
        if nadc < 0 or nadc > 1 :
            raise Exception('Wrong ADC chip number : %d. Should be 0 or 1' %(nadc))

        # bit 10 in micaroblase addr space - select adc chip : 0 -- ADC-1, 1-- ADC-2
        self.brd.pokenow(ADDR_ADCSPI_OFFSET | (nadc << 10) | (reg << 2), val)
    
    def GetAdcReg(self, nadc, reg):
        if reg < 0 or reg > 0xff :
            raise Exception('Wrong ADC register address : %d' % (reg))
        if nadc < 0 or nadc > 1 :
            raise Exception('Wrong ADC chip number : %d. Should be 0 or 1' %(nadc))
        if type(reg) != int : reg = int(reg,0)
        self.brd.pokenow(ADDR_ADCSPI_OFFSET | (nadc << 10), 2)
        val = self.brd.peeknow(ADDR_ADCSPI_OFFSET | (nadc << 10) | (reg << 2))
        self.brd.pokenow(ADDR_ADCSPI_OFFSET | (nadc << 10), 0)
        print(hex(val), file=sys.stderr)
        return val


    #####################################################
    # ADC control methods
    #####################################################
    def AdcSetNchMode(self, nadc = 0, ch_mode = 32):
        # See register 1h in datasheet
        if ch_mode != 32 and ch_mode != 16 :
            raise Exception('error: unsupported mode. Available modes are: 16, 32')

        lvds_mode = 0 << 14 # 1 for 2x mode
        sel_ch2   = 0 << 7
        sel_ch1   = 1 << 4 if ch_mode == 16 else 0
        sel_ch0   = 1 << 2 if ch_mode == 16 else 0
        glb_pdn   = 0 << 0 # 1 for power down
        val = sel_ch0 | sel_ch1 | sel_ch2 
        self.SetAdcReg(nadc, 1,val)

    def AdcSetPatSelInd(self, nadc, en_bit) :
        if en_bit > 1 or en_bit < 0 :
            raise Exception('''error: wrong parameter for PAT_SEL_IND bit.''')
        val = en_bit << 8
        
    def AdcSetMsbFirst(self, nadc, en_bit):
        # if en_bit > 1 or en_bit < 0 :
        if en_bit not in [0,1] :
            raise Exception('''error: wrong parameter for MSB first enable.\n 
            Should be 1 for MSB first mode or 0 for LSB first mode''');
            return
        val = en_bit << 4
        self.SetAdcReg(nadc, 4, val)

    def AdcTxTrg(self):
        val = 1 << C_CMD_ADCTXTRG_BIT
        self.RegWrite(CMD, val)

    def AdcReset(self):
        val = 1 << C_CMD_ADCRESET_BIT
        self.RegWrite(CMD, val)

    def AdcSetTestMode(self, nadc, imode, ch = -1):
        testPatModes = {
            'normal'   : 0, # normal ADC operation
            'sync'     : 1, # half frame 1, half frame 0
            'deskew'   : 2, # alternating 1 and 0
            'custom'   : 3, # custom pattern set by reg 5
            'allones'  : 4, # all 1s
            'toggle'   : 5, # toggle mode
            'allzeros' : 6, # all 0s
            'ramp'     : 7  # ramp mode
        }
        if imode in testPatModes.keys() :
            mode = testPatModes[imode]
            if ch == -1 : # all
                val = (mode & 7) << 7
                self.SetAdcReg(nadc, 0x2,val)
            elif ch == 0 : # frame
                val = (mode & 7) << 13
                self.SetAdcReg(nadc, 0x2,val)
                # val = (mode & 7) << 9
                # self.SetAdcReg(0x15,val)
        else :
            print('error: wrong test pattern mode. Alailable modes are:', file=sys.stderr)
            for imode in testPatModes.keys() :
                print(imode, file=sys.stderr)

    def AdcSetTestPat(self, nadc, pattern = 0) :
        ptrn = pattern & 0xfff;
        val  = pattern << 4;
        self.SetAdcReg(nadc, 5, val)

    def AdcInitCmd(self, nadc):
        # set INIT1 and INIT2 bits as part of initialization after power-up
        # see register 0xA description in the datasheet
        val = 0b11 << 12
        self.SetAdcReg(nadc, 0xA, val)

    def AdcSetSerDataRate(self, nadc, rate) :
        serDataRateModes = {
            12 : 0,
            14 : 0b001,
            16 : 0b100,
            10 : 0b011
        }
        if rate in serDataRateModes.keys() :
            val = serDataRateModes[rate] << 13
            self.SetAdcReg(nadc, 0x3, val)
        else :
            raise Exception('error: wrong SER_DATA_RATE value')

    def CalibrateIDelaysFrameAll(self) :
        frame_dly = [0,0]
        for iadc in range(0,2) :
            print("calibrate frame IDELAY for ADC #%d"%(iadc), file=sys.stderr)
            frame_dly[iadc] = self.CalibrateIDelayFrame(iadc)
        for iadc in range(0,2) :
            self.RegWrite(ADCFRAMEDELAY_0 + iadc*4, frame_dly[iadc])

    def CalibrateIDelaysDataAll(self) :
        for iadc in range(0,2) :
            print("calibrate data IDELAYs for ADC #%d"%(iadc), file=sys.stderr)
            ret = self.CalibrateIDelaysData(iadc)
            self.AdcSetTestMode(iadc, 'normal')
            if not ret:
                raise Exception('ADC calibration failed')

    def CalibrateIDelaysData(self, nadc)  :
        self.AdcSetTestMode(nadc, 'custom')
        itr = 0
        while itr < 10:
            bitslp = 0
            for chn in range(16) : 
                res = self.CalibrateIDelaySingle(nadc, chn)
                x = int(not res) << chn
                bitslp = bitslp | x
                #print(bin(bitslp))
            itr = itr + 1
            if bitslp == 0 : 
                print('Calibration OK', file=sys.stderr)
                self.AdcSetTestMode(nadc, 'normal')
                return True
            else :
                print('One more try with bitslip %s' % (bin(bitslp)), file=sys.stderr)
                self.RegWrite(BITSLIP+nadc*4, bitslp)
        print('Failed', file=sys.stderr)
        return False


    def CalibrateIDelaySingle(self, nadc, chn):
        self.RegWrite(ADCDEBUGCHAN, nadc*32 + chn*2) 
        dly_good_first = -1
        dly_good_last = -1
        for dly in range(0,0x20) :
            self.RegWrite(ADCDATADELAY_0 + 16*nadc*4 + 4*chn, dly)
            res = self.CheckPattern(nadc, self.TestPattern[0]) 
            # res2 = self.CheckPattern(nadc, self.TestPattern[1]) 
            
            if res : 
                if dly_good_first == -1 : dly_good_first = dly
                dly_good_last = dly
        if dly_good_first != -1 :
            dly_best = int((dly_good_first+dly_good_last)/2)
            print("Channel %d : dly_good_first = %d dly_good_last = %d best = %d" 
                % (chn, dly_good_first, dly_good_last, dly_best), file=sys.stderr)
            self.RegWrite(ADCDATADELAY_0 + 16*nadc*4 + 4*chn, dly_best)
            return True
        else:
            print('No delay found for channel %d' % (chn), file=sys.stderr)
            return False

    def CalibrateIDelayFrame(self, nadc):
        dly_good_first = -1
        dly_good_last  = -1
        dly_seqs = []
        i = 0
        dly_prev_bad = False
        for dly in range(0,0x20) :
            self.RegWrite(ADCFRAMEDELAY_0+nadc*4, dly)
            time.sleep(0.001)
            sta = self.RegRead(STATUS) & (1 << nadc)
            if sta != 0 :
                if dly_prev_bad : i = i + 1
                if len(dly_seqs) < i+1 :
                    dly_seqs.append([])
                dly_seqs[i].append(dly)
                dly_prev_bad = False
            else :
                if len(dly_seqs) != 0 : dly_prev_bad = True
        print(dly_seqs, file=sys.stderr)
        if len(dly_seqs) != 0:
            dly_lens = [len(s) for s in dly_seqs]
            imax = dly_lens.index(max(dly_lens))
            print(imax, file=sys.stderr)
            dly_best = (dly_seqs[imax][0] + dly_seqs[imax][-1])/2
            print("ADC %d frame delay : dly_good_first = %d dly_good_last = %d best = %d" 
                 % (nadc, dly_seqs[imax][0], dly_seqs[imax][-1], dly_best), file=sys.stderr)
            return int(dly_best)

        else:
            raise Exception('No delay found for frame signal for ADC#%d'%(nadc))
        

    def CheckPattern(self, nadc, pattern):
        self.AdcSetTestPat(nadc, pattern)
        for i in range(0,self.NCalSamples) :
            val = self.RegRead(ADCDEBUG1)
            if val != pattern :
                return False
        return True

    #####################################################
    # DRS control
    #####################################################
    def DrsTransperentMode(self, mode_on):
        self.RegSetBit(MODE,C_MODE_DRS_TRANS_BIT,mode_on)

    def DrsSetConfigReg(self):
        self.RegWrite(ADDR_DRSCFG_OFFSET,0b11111111)

    def DrsSetWriteReg(self):
        self.RegWrite(ADDR_DRSCFG_OFFSET + 4,0xff)

    #####################################################
    # ADC buffer control
    #####################################################
    def AdcBufStart(self):
        self.RegSetBit(MODE,C_MODE_ADCBUF_WREN_BIT,1)

    def AdcBufStop(self) :
        self.RegSetBit(MODE,C_MODE_ADCBUF_WREN_BIT,0)
            
    def ReadMem(self, start_addr, num_words, chan = -1, fname = "") :
        ret_val = []
        self.AdcBufStop();
        
        if chan != -1 :
            if not self.SetDebugChan(chan) : return -1

        if fname != "" : filo = open(fname,"w+")

        addr = ADDR_ADCBUF_OFFSET + (1<<2)
        v = self.RegRead(addr)
        
        for i in range(0,num_words):
            # FIXME use multiple peek followed by transfer
            # addr = ADDR_ADCBUF_OFFSET + ((start_addr + i)<<2)
            addr = ADDR_ADCBUF_OFFSET 
            rv = self.RegRead(addr)
            v  = rv >> 4
            f  = rv & 0xf
            # convert two's compliment to signed int
            if f == 0 : 
              if v & (1<<11) != 0 : v = v - 0xfff - 1
            else : 
              if f == 1 : 
                v = -9999
              else : 
                v = 9999
              
            ret_val.append(v)
            if fname != "" : filo.write("%d %d\n" % (i, v))
        #self.AdcBufStart()
        return ret_val 

    def ReadWf(self) :
        raw = self.ReadMem(0, 4200, 15)
        wf  = [0]*1024
        for isa in range(0,1024):
            wf[isa] = raw[self.AdcSampleOffset + 4*isa] - int(self.peds[isa])
        return wf
    #####################################################
    # DAC configuration
    #####################################################
    
    # convert voltage to DAC code
    def GetDacCode(self, VOut = 0):
        DAC_NBITS = 12  # DAC60508
        dacDiv    = 1   # default
        dacGain   = 1   # 1 by default (?)
        DAC_VREF  = 2.5
        dacCode = int(0xffff/2.5*VOut)
        return int(dacCode)

    # initialize DAC
    def DacIni(self, i = 0):
      if not 0 <= i <= 1 :
        print('error :: wrong DAC number')
        return False
      dac_num_addr = (i << 4)
      self.RegWrite(ADDR_DAC_OFFSET | ((0x4 | dac_num_addr)<<2),0x1ff)

    # set output voltage
    def DacSetVout(self, dac_num, dac_chn, vout):

        if type(dac_chn) == int :
            dac_chn_i = dac_chn
        elif type(dac_chn) == str :
            dac_chn_i = self.DACOUTS[dac_chn]
        else :
            raise Exception('dac_chn should be integer or string')

        if dac_chn_i < 0 or dac_chn_i > 7 :
            raise Exception('ERROR:: Wrong DAC channel')

        if not 0 <= dac_num <= 1 :
            print('error :: wrong DAC number')
            return False

        dac_num_addr = (dac_num << 4)

        addr = ADDR_DAC_OFFSET | ((8 | dac_chn_i | dac_num_addr)<<2)
        val  = self.GetDacCode(vout)
        print('#%d DAC out: %d addr: %s voltage: %f code: %s' % (dac_num, dac_chn_i, hex(addr), vout, hex(val)), file=sys.stderr)
        self.RegWrite(addr, val)

    # set all voltages to operating values
    def DacSetAll(self):

        # initialize DAC first to be sure that we are not going to burn anything
        self.DacIni()

        # set output voltages TODO: don't hardcode values here
        for i in range(2) : 
            self.DacSetVout(i, 0,0.7)   # BIAS
            self.DacSetVout(i, 1,1.55)  # ROFS
            self.DacSetVout(i, 2,0.8)   # OOFS
            self.DacSetVout(i, 3,0.8) # CMOFS
            self.DacSetVout(i, 4,0.8) #TCAL_N1
            self.DacSetVout(i, 5,0.8) #TCAL_N2

        

    # set all voltages to 0
    def DacClearAll(self) :
        for i in range(8) : self.DacSetVout(i,0)

        

    #####################################################
    # LAPPD configuration
    #####################################################

    def SetDrsRefClkRatio(self, ratio):
        self.RegWrite(DRSREFCLKRATIO,ratio)
    
    def GetMode(self):
        v = self.RegRead(MODE)
        return v
    
    def DrsTimeCalibOscOn(self):
        self.RegSetBit(MODE, C_MODE_TCA_ENA_BIT, 1)
    
    def DrsTimeCalibOscOff(self):
        self.RegSetBit(MODE, C_MODE_TCA_ENA_BIT, 0)

    def SetDebugChan(self, chan) :
        if chan < 0 or chan > 64 :
            raise Exception('wrong channel number')
            return False 
        self.RegWrite(ADCDEBUGCHAN,chan)
        return True

    def MeasurePeds(self, ch = 0, nev = 5):
        self.RegWrite(ADCBUFNUMWORDS,1025)
        self.RegSetBit(MODE, C_MODE_DRS_DENABLE_BIT,1)

        bufs = [[0]*nev for i in range(1024)]

        for i in range(nev) :
            print(i, file=sys.stderr)
            self.RegSetBit(CMD, C_CMD_READREQ_BIT, 1)
            time.sleep(0.001)
            v = self.ReadMem(0,1024,ch)
            # print(v)
            for isample in range(0,1024) :
                bufs[isample][i] = v[self.AdcSampleOffset + isample]
        
        print(bufs, file=sys.stderr)

        for isa in range(0,1024):
            buf = bufs[isa]
            mean = np.around(np.mean(buf),1)
            bufx = [(a - mean) for a in bufs[isa]]
            rms = np.around(np.sqrt(np.mean(np.square(bufx))),1)
            self.peds[isa] = mean
            self.rmss[isa] = rms
        #print(self.peds)
        print(self.rmss, file=sys.stderr)

    def MeasurePedsROI(self, ch = 0, nev = 5):
        self.RegWrite(ADCBUFNUMWORDS,1024)
        self.RegSetBit(MODE, C_MODE_DRS_DENABLE_BIT,1)

        bufs = [[0]*nev for i in range(1024)]

        idrs = int(ch/8)

        for i in range(nev) :
            print(i, file=sys.stderr)
            self.RegSetBit(CMD, C_CMD_READREQ_BIT, 1)
            time.sleep(0.001)
            v0   = self.ReadMem(0,1024,ch)
            stop = self.RegRead(DRSSTOPSAMPLE_0 + 4*idrs)
            v = v0[1023-stop+1 :] + v0[:1023-stop+1]
            for isample in range(0,1024) :
                bufs[isample][i] = v[isample]
        
        # print(bufs, file=sys.stderr)

        for isa in range(0,1024):
            buf = bufs[isa]
            mean = np.around(np.mean(buf),1)
            bufx = [(a - mean) for a in bufs[isa]]
            rms = np.around(np.sqrt(np.mean(np.square(bufx))),1)
            self.peds_roi[isa] = mean
            self.rmss_roi[isa] = rms
        #print(self.peds)
        # print(self.rmss, file=sys.stderr)

    def DumpEvents(self, nev = 5, ch = 0, fname = 'evdump.txt', reorder = True):
        self.RegWrite(ADCBUFNUMWORDS,1024)
        self.RegSetBit(MODE, C_MODE_DRS_DENABLE_BIT,1)

        idrs = int(ch/8)
        vm = [1024]

        f = open(fname, 'w')
        f.write('stop/D:a[1024]/D\n')
        for i in range(nev) :
            self.RegSetBit(CMD, C_CMD_READREQ_BIT, 1)
            time.sleep(0.001)
            v = self.ReadMem(0,1024,ch)
            stop = self.RegRead(DRSSTOPSAMPLE_0 + 4*idrs)
            if reorder :
              # vstr = str(stop) + ' ' + ' '.join(str(x) for x in v[1023-stop+1 :] ) 
              # vstr += ' ' + ' '.join(str(x) for x in v[:1023-stop+1]) + '\n'
               #upto = 1024-self.drs4_stop
               #self.cachedView[self.drs4_stop:] = self.payload[:upto]
               #self.cachedView[0:self.length - upto] = self.payload[upto:]
              vm[stop:] = v[:1024-stop]
              vm[0:stop] = v[1024-stop:]
              vstr = str(stop) + ' ' + ' '.join(str(x) for x in vm) + '\n'

            else : 
              vstr = str(stop) + ' ' + ' '.join(str(x) for x in v) + '\n'
              
            f.write(vstr)
            print(i, end = ' ', flush = True)
        print('\n')
        f.close()

    def DumpPeds(self,ch = 0,nev = 100) :
        self.MeasurePeds(ch,nev)
        self.MeasurePedsROI(ch,nev)
        f = open('peds.txt','w')
        f.write('cap : p_f/D : rms_f/D : p_r/D : rms_r/D \n')
        for i in range(1024) :
            f.write('%d %0.2f %0.2f %0.2f %0.2f \n' % (i,self.peds[i],self.rmss[i],self.peds_roi[i],self.rmss_roi[i]))
        f.close()


    def Initialize(self, doCal = True):
        fwver = self.RegRead(FW_VERSION) & 0xff
        
        print('FW version : %d' % (fwver), file=sys.stderr)

        # reset logic
        self.RegSetBit(MODE,11,1)
        time.sleep(0.2)
        self.RegSetBit(MODE,11,0)
        time.sleep(0.2)
        self.RegWrite(CMD, 1 << C_CMD_RESET_BIT);

        # switch external triggering off
        self.RegSetBit(MODE, C_MODE_EXTTRG_EN_BIT, 0);
        self.RegSetBit(MODE, C_MODE_DRS_TRANS_BIT, 0)

        #initialize ADC
        self.AdcReset()
        self.AdcInitCmd(0) # ADC1
        self.AdcInitCmd(1) # ADC2
        self.AdcTxTrg()


        # set DAC voltages
        self.DacIni()
        self.DacSetAll()

        # self.RegSetBit(CMD, C_CMD_ADCRDRESET_BIT, 1)
        if fwver >= 100 and doCal : self.CalibrateIDelaysFrameAll()
        # reset bitslips for ISERDESEs on data lines
        # self.RegSetBit(CMD, C_CMD_ADCRDRESET_BIT, 1)
        if doCal : self.CalibrateIDelaysDataAll()

        self.RegWrite(DRSREFCLKRATIO, self.drsrefclk)
        # print("DRSREFCLKRATIO : %d" % (self.drsrefclk), file=sys.stderr)

        # initialize DRS-4 chips 
        self.DrsSetConfigReg()
        # enable DRS-4 transparent mode
        self.RegSetBit(MODE, C_MODE_DRS_TRANS_BIT, 0)
        print('DRS4 transparent mode is OFF', file=sys.stderr)
        # set DENABLE
        self.RegSetBit(MODE, C_MODE_DRS_DENABLE_BIT, 1)
        print('DENABLE is ON', file=sys.stderr)

        time.sleep(0.01)
        pll = self.RegRead(DRSPLLLCK) & 0xff

        if pll != 0xff : 
            print('error:: DRS4 PLL failed to lock : %s' % (bin(pll)), file=sys.stderr)
        else : 
            print('DRS4 PLL locked', file=sys.stderr)

        # tune SRCLK to ADCCLK phase
        if fwver >= 105 :
            self.RegWrite(DRSVALIDDELAY, 65) # for the first sample extended
            self.RegWrite(DRSADCPHASE, 1)
            self.RegWrite(DRSWAITADDR, 12) 
        if fwver >= 100 :
            self.RegWrite(DRSVALIDDELAY, 36) # for the first sample extended
            self.RegWrite(DRSWAITADDR, 12) 
        else :
            # remove this once new version is stable
            self.RegWrite(DRSREFCLKRATIO, self.drsrefclk)
            self.RegWrite(DRSVALIDDELAY,44)
            self.RegWrite(NSAMPLEPACKET, 512) # number of words in packet

        # ROI readout mode
        self.RegWrite(ADCBUFNUMWORDS,1024)
        print('ROI readout mode', file=sys.stderr)
        
        self.RegWrite(ADCCHANMASK_0  , self.mask_adc1)
        self.RegWrite(ADCCHANMASK_0+4, self.mask_adc2)

        print("ADC1 mask: %s ADC2 mask: %s" % (bin(self.mask_adc1), bin(self.mask_adc2)), file=sys.stderr)


        # to switch TCA on : 
        # self.DrsTimeCalibOscOn():

        # send software trigger:
        #ifc.RegSetBit(CMD, C_CMD_READREQ_BIT, 1)
        



