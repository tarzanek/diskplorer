#!/usr/bin/python3

from __future__ import print_function

import os
import json
import subprocess
import matplotlib
import math
import optparse
import multiprocessing
import re

matplotlib.use('svg')  # must come before pyplot import

import matplotlib.pyplot as plt

optparser = optparse.OptionParser()

optparser.add_option('-d', '--mountpoint', dest='mountpoint', default='.',
                     help='Test disk mounted at MOUNTPOINT', metavar='MOUNTPOINT')
optparser.add_option('-t', '--test', dest='test_name', default='randread', choices=['read', 'write', 'randwrite', 'randread'],
                     help='Test to run', metavar='TEST')
optparser.add_option('-b', '--device', dest='device', default=None,
                     help='Test block device DEV (overrides --mountpoint)', metavar='DEV')
optparser.add_option('-s', '--filesize', dest='filesize', default='100G',
                     help='Set SIZE as file size for test', metavar='SIZE')
optparser.add_option('--buffer-size', dest='buffer_size', default='4k',
                     help='Set SIZE as I/O buffer size for test (ex. 4k, 1M)', metavar='SIZE')
optparser.add_option('-m', '--max-concurrency', dest='maxdepth', default=128, type='int',
                     help='Test maximum concurrency level N', metavar='N')
optparser.add_option('-o', '--output', dest='output_filename', default='disk-concurrency-response.svg',
                     help='Write output graph to FILE', metavar='FILE')
optparser.add_option('--raw-results', dest='raw_results_filename',
                     metavar='FILE', default='disk-concurrency-response.csv',
                     help='Write raw results (.csv) to FILE')

(options, args) = optparser.parse_args()

mountpoint = options.mountpoint
filesize = options.filesize
maxdepth = options.maxdepth
buffer_size = options.buffer_size
output_filename = options.output_filename
raw_filename = options.raw_results_filename
test_name = options.test_name
input_filename = 'fiotest.tmp'
readonly = []
stat_label = 'read'

if re.search('write', test_name):
    stat_label = 'write'

if options.device:
    input_filename = options.device
    readonly = ['--readonly']
    mountpoint = '/'

header = '''\
[global]
ioengine=libaio
buffered=0
rw={test_name}
bs={buffer_size}
size={filesize}
directory={mountpoint}
runtime=10s
filename={input_filename}
group_reporting=1

'''

job_template = '''\
[{jobname}]
iodepth={depth}
{new_group}

'''

max_threads = multiprocessing.cpu_count()

def create_fio_spec(fname):
    with open(fname, 'w') as f:
        f.write(header.format(**globals()))
        depth = 1
        growth = 1.05
        while depth <= maxdepth:
            depth_remain = depth
            threads_remain = max_threads
            new_group = 'stonewall'
            # distribute load among max_threads
            while depth_remain:
                depth_now = int(depth_remain / threads_remain)
                if depth_now:
                    f.write(job_template.format(jobname=depth, depth=depth_now, new_group=new_group))
                    new_group = ''
                    depth_remain -= depth_now
                threads_remain -= 1
            depth = int(max(math.ceil(depth * growth), depth + 1))

def run_job():
    spec_fname = 'tmp.fio'
    create_fio_spec(spec_fname)
    result_json = subprocess.check_output(['fio', '--output-format=json'] + readonly + [spec_fname])
    result_json = result_json.decode('utf-8')
    open('tmp.fio.json', 'w').write(result_json)
    return json.loads(result_json)


results = run_job()

concurrencies = [0]  # FIXME: fake 0 element to force axis limit
latencies = [0.]
latencies_05 = [0.]
latencies_95 = [0.]
iopses = [0.]

for job in results['jobs']:
    concurrency = int(job['jobname'])
    latency = float(job[stat_label]['clat_ns']['mean'])
    latency_05 = float(job[stat_label]['clat_ns']['percentile']['5.000000'])
    latency_95 = float(job[stat_label]['clat_ns']['percentile']['95.000000'])
    latency_stddev = float(job[stat_label]['clat_ns']['stddev'])
    iops = float(job[stat_label]['iops'])
    concurrencies.append(concurrency)
    latencies.append(latency)
    latencies_05.append(latency_05)
    latencies_95.append(latency_95)
    iopses.append(iops)

def fix_y_axis(plt):
    plt.ylim(0.0, plt.ylim()[1])

fig, ax1 = plt.subplots()
ax1.plot(concurrencies, iopses, 'b-+')
ax1.set_xlabel('concurrency')
# Make the y-axis label and tick labels match the line color.
ax1.set_ylabel('{buffer_size} {stat_label} iops'.format(**globals()), color='b')
for tl in ax1.get_yticklabels():
    tl.set_color('b')
# FIXME: want log scale on X axis

ax2 = ax1.twinx()
#ax2.plot(concurrencies, latencies, 'r-+')
ax2.errorbar(concurrencies, latencies, yerr=[latencies_05, latencies_95], color='r')
ax2.set_ylabel(u'average latency (ns)', color='r')
for tl in ax2.get_yticklabels():
    tl.set_color('r')

plt.tight_layout()
plt.savefig(fname=output_filename)

with open(raw_filename, 'w') as raw:
    print('buffersize,concurrency,iops,lat_avg,lat_05,lat_95', file=raw)
    for concurrency, iops, lat_avg, lat_05, lat_95 in zip(
            concurrencies, iopses, latencies, latencies_05, latencies_95):
        print('{buffer_size},{concurrency},{iops},{lat_avg},{lat_05},{lat_95}'
              .format(**locals()), file=raw)
