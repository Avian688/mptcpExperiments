"""Path-resolved redistribution, per-link busy fraction, goodput and HoL."""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from plotAlphaValidation import read, load, sample, subflows, save, mean_variance
from experimentProtocols import PROTOCOLS, CC_LABELS, CC_COLORS
from redistributionExperiments import (SIM_ROOT, DURATION, STEP, topology, cases,
    configurations, phases, waves, reference, forward_interfaces)

COLORS = ('#0072B2', '#E69F00', '#009E73', '#882255')


def bin_busy(series, edges):
    """Integrate PPP's 0/1 transmission state, rather than mistake U for occupancy."""
    t, v = series
    if not len(t): return np.full(len(edges)-1, np.nan)
    # PPP begins idle; the last state persists until the simulation limit.
    if t[0] > 0:
        t, v = np.r_[0., t], np.r_[0., v]
    cumulative = np.r_[0., np.cumsum(np.diff(t)*v[:-1])]
    idx = np.maximum(0, np.searchsorted(t, edges, side='right')-1)
    integral = cumulative[idx] + (edges-t[idx])*v[idx]
    return np.diff(integral)/np.diff(edges)


def goodput(root, i, grid):
    traces = load(root, f'server[{i}].app[0]', 'goodput')
    return np.sum([sample(s, grid, True) for _, s in traces], axis=0)/1e6 if traces else np.full(grid.shape, np.nan)


def decorate(ax, number, case, ylabel):
    for start, stop, label in phases(number, case):
        if 'competition' in label:
            ax.axvspan(start, stop, color='grey', alpha=.12)
    ax.set(xlabel='Time (s)', ylabel=ylabel, xlim=(0,DURATION))
    ax.grid(alpha=.2)
    ax.set_ylim(bottom=0)
    if ax.get_legend_handles_labels()[0]: ax.legend(fontsize=8)


def diagnostics(root, output, number, case, protocol, run, grid, curves):
    names = topology(number)[2]
    title = f'{CC_LABELS[protocol]} — {case} — run {run}'
    edges = np.arange(0, DURATION+STEP, STEP)
    fig, axes = plt.subplots(2,2,figsize=(13,7), sharex=True)
    for i, ax in enumerate(axes.flat):
        ax.plot(grid, curves[i], label='Goodput', color=COLORS[i])
        ax.plot(grid, [reference(number,case,t)[i] for t in grid], ls='--', color='grey', label='Ideal connection max–min')
        ax.set_title(names[i]); decorate(ax,number,case,'Goodput (Mbps)')
    fig.suptitle(title); save(fig, output/'goodput')
    fig, axes = plt.subplots(2,2,figsize=(13,7), sharex=True)
    for i, ax in enumerate(axes.flat):
        for j, (a,b) in enumerate(topology(number)[1][i]):
            traces=load(root,f'client[{i}].ppp[{j}].ppp','transmissionState')
            if traces:
                # Access link is 10 Gbps; bytes on the wire, not app goodput.
                rate=bin_busy(traces[0][1],edges)*10000
                label=f'L{a//2+1}' if number==6 else f'Lane {j+1}'
                ax.plot(grid,rate,label=label,lw=.8)
        ax.set_title(names[i]); decorate(ax,number,case,'Subflow wire sending rate (Mbps)')
        if not ax.lines: ax.text(.5,.5,'No recorded path samples',transform=ax.transAxes,ha='center')
    fig.suptitle(title); save(fig,output/'subflow_rates')
    fig,axes=plt.subplots(2 if number==7 else 1,1,figsize=(12,6),squeeze=False,sharex=True)
    for i,(interface,label) in enumerate(forward_interfaces(number)):
        traces=load(root,f'{interface}.ppp','transmissionState')
        if traces: axes[i//3 if number==7 else 0,0].plot(grid,100*bin_busy(traces[0][1],edges),label=label,lw=.8)
    for ax in axes.flat:
        decorate(ax,number,case,'Link busy time (%)');ax.set_ylim(0,105)
    fig.suptitle(title);save(fig,output/'link_utilisation')
    for metric, scale, ylabel, receiver in (
        ('cwnd',1024,'Cwnd (KiB)',False), ('U',1,'Path U',False),
        ('srtt',.001,'Smoothed RTT (ms)',False),
        ('throughput',1e6,'Subflow in-order delivery (Mbps)',True),
        ('subflowSendQueueBytes',1024,'Unsent send queue (KiB)',False),
        ('holBlockedBytes',1024,'Receiver HoL (KiB)',True)):
        fig,axes=plt.subplots(2,2,figsize=(13,7),sharex=True)
        for i,ax in enumerate(axes.flat):
            if receiver:
                traces=load(root,f'server[{i}].tcp',metric)
            else:
                traces=[(p.name,read(p/f'{metric}.csv',metric)) for p in subflows(root,f'client[{i}]') if (p/f'{metric}.csv').exists()]
            for name,(t,v) in traces: ax.step(t,v/scale,where='post',label=name.rsplit('.',1)[-1],lw=.7)
            if not traces: ax.text(.5,.5,'Not recorded / not applicable',transform=ax.transAxes,ha='center')
            ax.set_title(names[i]);decorate(ax,number,case,ylabel)
        fig.suptitle(title);save(fig,output/metric)
    for metric,label in (('queueLength','Queue length (packets)'), ('pintLocalUtilization','Switch U')):
        fig,axes=plt.subplots(2 if number==7 else 1,1,figsize=(12,6),squeeze=False,sharex=True)
        for i,(interface,name) in enumerate(forward_interfaces(number)):
            for _,(t,v) in load(root,f'{interface}.queue',metric):
                axes[i//3 if number==7 else 0,0].step(t,v,where='post',label=name,lw=.8)
        for ax in axes.flat:decorate(ax,number,case,label)
        fig.suptitle(title);save(fig,output/metric)
    if not waves(number,case):return
    fig,ax=plt.subplots(figsize=(11,4))
    for i,start,stop in waves(number,case):
        ax.plot(grid,goodput(root,i,grid),label=f'Background {i-3}',lw=.8)
    decorate(ax,number,case,'Background goodput (Mbps)');save(fig,output/'background_goodput')


def main(number):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs',nargs='+',type=int,default=list(range(1,6)))
    parser.add_argument('--configs',nargs='+',default=[c[0] for c in configurations(number)])
    parser.add_argument('--csv-root',type=Path,default=SIM_ROOT/f'experiments/experiment{number}/csvs')
    parser.add_argument('--out-dir',type=Path,default=SIM_ROOT/f'plots/experiment{number}')
    args=parser.parse_args()
    if set(args.configs)-{c[0] for c in configurations(number)}:parser.error('Unknown configurations')
    args.out_dir.mkdir(parents=True,exist_ok=True)
    grid=np.arange(STEP/2,DURATION,STEP)
    rows=[]; stats=[]; averaged={};coverage=[]
    for protocol in PROTOCOLS:
        for case in cases(number):
            if f'{protocol}_{case}' not in args.configs:continue
            collected=[]
            output=args.out_dir/protocol/case.lower()
            for run in args.runs:
                root=args.csv_root/protocol/case.lower()/f'run{run}'
                curves=np.array([goodput(root,i,grid) for i in range(4)])
                present=bool(np.all(np.any(np.isfinite(curves),axis=1)))
                coverage.append(dict(protocol=protocol,case=case,run=run,all_connections_present=present))
                if not present:continue
                diagnostics(root,output/f'run{run}',number,case,protocol,run,grid,curves)
                collected.append(curves)
                for start,stop,phase in phases(number,case):
                    # Final ten seconds of each phase; missing data stays unknown.
                    window=(grid>=stop-10)&(grid<stop-STEP)
                    for i,name in enumerate(topology(number)[2]):
                        vals=curves[i,window]; valid=np.isfinite(vals)
                        rows.append(dict(protocol=protocol,case=case,run=run,phase=phase,connection=name,
                            coverage=valid.mean(),goodput_mbps=np.nanmean(vals) if valid.mean()>=.95 else np.nan,
                            ideal_maxmin_mbps=reference(number,case,stop-1)[i]))
            if collected:
                mean,var,count=mean_variance(np.array(collected))
                averaged[protocol,case]=(mean,var)
                fig,axes=plt.subplots(4,2,figsize=(14,12),sharex=True)
                for i,name in enumerate(topology(number)[2]):
                    sd=np.sqrt(var[i]);ax=axes[i,0]
                    ax.plot(grid,mean[i],color=COLORS[i],label=name)
                    ax.fill_between(grid,mean[i]-sd,mean[i]+sd,color=COLORS[i],alpha=.2)
                    decorate(ax,number,case,'Goodput mean ± SD (Mbps)')
                    axes[i,1].plot(grid,var[i],color=COLORS[i]);decorate(axes[i,1],number,case,'Variance (Mbps²)')
                    stats.extend(dict(protocol=protocol,case=case,connection=name,time_s=t,mean_mbps=m,variance_mbps2=v,runs=n)
                                 for t,m,v,n in zip(grid,mean[i],var[i],count[i]))
                fig.suptitle(f'{CC_LABELS[protocol]} — {case}');save(fig,output/'goodput_mean_variance')
    for case in cases(number):
        if not any(c==case for _,c in averaged):continue
        fig,axes=plt.subplots(2,2,figsize=(14,8),sharex=True)
        for i,ax in enumerate(axes.flat):
            for protocol in PROTOCOLS:
                if (protocol,case) in averaged:
                    mean,_=averaged[protocol,case]
                    ax.plot(grid,mean[i],label=CC_LABELS[protocol],color=CC_COLORS[protocol],lw=1)
            ax.plot(grid,[reference(number,case,t)[i] for t in grid],color='grey',ls='--',label='Ideal max–min')
            ax.set_title(topology(number)[2][i]);decorate(ax,number,case,'Mean goodput (Mbps)')
        fig.suptitle(case);save(fig,args.out_dir/f'comparison_{case.lower()}')
    pd.DataFrame(rows).to_csv(args.out_dir/'phase_summary.csv',index=False)
    pd.DataFrame(stats).to_csv(args.out_dir/'goodput_time_statistics.csv',index=False)
    pd.DataFrame(coverage).to_csv(args.out_dir/'coverage.csv',index=False)
    if not averaged:print('No complete connection goodput found.');return 1
    return 0
