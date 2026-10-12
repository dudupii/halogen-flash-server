# Troubleshooting

## If the server will not start: "out of memory"

A start that ends in

```
dmalloc: FAILED requesting 0.750 GiB after 39.703 GiB in 647 allocations (out of memory)
HIP /src/halogen/src/flash_ops.h:122: out of memory
```

means the KV pool did not fit on this machine. **`HALOGEN_KV_SLOTS` will not
fix it** and is the first thing most people try: since 0.3 the slots share one
pool and each costs only about 115 MB, so one slot allocates as much as four.
The knob is the pool:

```
-e HALOGEN_KV_POOL_POSITIONS=262144
```

That is about 20 GiB on the device, the same layout 0.2.0 ran, and it still
serves four conversations at once. `524288` is about 27 GiB and is the
default. If it still will not start, halve the prefill call as well with
`-e HALOGEN_MAX_TOK=16384`, which gives back about 4.4 GiB on the default
checkpoint (the startup line's working memory goes from 12.6 to 8.1 GiB,
and w4b gives back 1.5) for about 9% of prefill speed; the [memory
section](configuration.md#context-and-memory-one-kv-pool-several-conversations) has the
measured table.

A start that ends in `checkpoint: refusing to pin ... the floor is 16.00
GiB` instead is the same arithmetic one step later: everything fit except
the last pin, and finishing it would leave the host under 16 GiB, where the
lookup table pages in from disk on every long prompt. Since 0.11.9 that line
says how far short the configuration is and lists the levers in order;
`HALOGEN_MAX_TOK=16384` is usually the one. A K-quant GGUF on a 122 GiB box
is the case that found it (issue #80): the pool was already at one context,
so the pool fit had nothing to lower, and the pre-flight estimate carried
the smaller GGUF's weight size.

## If the server hangs at "reserving the KV pool"

A start that prints `reserving the KV pool` and then nothing for many
minutes, with `still reserving` lines whose compaction counts climb and a
process that `podman stop` cannot end, is not the out-of-memory case above.
The pool lands in GTT, the driver's own window on system RAM, and a start
that cannot place it there does not fail: it blocks inside the driver. On
four hosts (issues #34 and #79, and our own gate machine) the cause was
memory a previous GPU process's exit did not give back: a process ending
while the GPU had work in flight (another model's exit, a watchdog kill
under a memory stall, a `podman restart` mid-reservation, a cancelled
request on a busy queue), after which 35 to 45 GiB of GTT stayed allocated
with no process alive, on two of them with a kernel worker
(`svm_range_restore_work`) in uninterruptible sleep. Since 0.11.9 the
container reads the driver's counters before it starts and says so:

```
halogen: GTT in use before this start: 34.9 GiB of 120.0 (85.1 free; this start puts about 31.6 GiB there)
halogen: WARNING 34.9 GiB of GTT is in use and no process holds the GPU, as far as this container can see
```

If that warning appears, check on the host (not in the container) that
nothing holds the device, `fuser -v /dev/kfd`, and that the figure does not
fall on its own, `cat /sys/class/drm/card*/device/mem_info_gtt_used`.
Removing containers does not release it and neither does waiting; reboot the
host before starting the server again. When the GTT is held by another
process the line says that instead, and the server starts on what is left;
when what is left is less than the pool needs, it refuses at once rather
than blocking. What puts a host there is the kill, and since 0.11.9 the
watchdog no longer kills an engine that is silent inside the kernel (see
[Give it a machine of its own](host-setup.md#give-it-a-machine-of-its-own)). A start
that grinds at `reserving the KV pool` with `compaction stalls` climbing
and no GTT held is the other case: the host's free memory is not in
contiguous pieces large enough (other processes hold it), and freeing them
lets the reservation complete at once. That, and the stalls and wedges the
same pressure causes while serving, are tracked in issue #85.

A GPU memory fault (`Memory access fault by GPU node-1 ... Page not present`)
is a different failure, and since 0.12.2 the container ends it in seconds:
on 0.12.1 and earlier the bundled runtime then wrote a GPU core dump of the
whole process (`GPU coredump: ... Falling back to file-based dump`), which
for a process with over 100 GiB mapped is minutes in uninterruptible sleep
before the engine can exit, read by the watchdog as the memory case above.
The container now disables that dump and the process's core file, so the
fault line is followed by the engine's exit and the takedown path, and the
log holds the fault's own decode (issue #83). The fault itself is reported
on one host (kernel 7.2.5) and not reproduced on the reference host (7.1.8);
if you see it, the fault line and `uname -r` are what a report needs.

## If the server starts but crawls on long prompts

A server that starts, answers short prompts, and then collapses to a few
tokens per second on a long one, with the disk busy and the process stuck in
uninterruptible sleep, is short of file cache rather than short of memory.
The model keeps a large lookup table on disk and reads it through the page
cache instead of holding it in RAM, so RAM the KV pool takes is RAM that
table loses, and a longer prompt touches more of it. Since 0.6.3 the rows a
prompt needs are read 64 at a time, so a table that is not in the cache costs
seconds on an NVMe drive rather than minutes, and the log says how long each
long prompt spent on it (`lookup table: ... took N s on 64 threads`). If that
line still reads in the tens of seconds, the drive is the limit, and the same
setting helps:

```
-e HALOGEN_KV_POOL_POSITIONS=262144
```

`HALOGEN_HOST_RESERVE_GIB` (default 20) is how much RAM the server leaves
free for that cache when it sizes the pool at startup; raising it makes the
server choose a smaller pool on its own.

**Check the BIOS before you tune anything, if this machine carves memory out
for the iGPU.** A fixed block assigned to graphics in firmware is taken before
the kernel boots, so it never shows up as missing anywhere on the host: the
machine just reports itself smaller, and that RAM is gone from the file cache
the lookup table depends on. **This server does not need it.** It drives the
GPU through GTT and allocates from the same unified memory whichever way the
setting is left, so a large carve-out buys nothing here and costs cache. Set
the UMA frame buffer or dedicated graphics memory option to its explicit
MINIMUM, not to Auto: on the reference machine the minimum reports about
512 MiB, on a GMKtec EVO-X2 it is 2 GB, and on that board "Auto" turned out
to be 64 GiB (the OS saw 61 GiB of a 128 GB machine and the weights could
not load until the setting was changed).

You are paying for a carve-out even when nothing has thrashed yet. The pool
sizes itself from the memory total the OS reports, which the carve-out has
already made smaller, so the server quietly chooses a smaller pool and keeps
fewer conversations resident than [the pool table](configuration.md#context-and-memory-one-kv-pool-several-conversations) says. Pin the pool yourself
and the file cache takes the whole loss instead. Either way the server prints
what it found at startup, and warns when it is large:

```
memory: 16.0 GiB of this machine's RAM is carved out for the iGPU in firmware.
        That is not free memory the OS can lend to the file cache above, and
        it does not appear anywhere in /proc/meminfo: the machine simply
        reports itself smaller
```

Device memory here is system memory, and the ceiling is set by the kernel's
resident-memory limit rather than by anything a driver reports: measured at
about 47 GB on a 128 GB machine, and lower on machines carrying more besides
this server. From 0.3.1 the server measures that budget at startup and lowers
the pool itself when the configured one will not fit, printing what it chose;
`HALOGEN_KV_POOL_FIT=0` turns that off and allocates exactly what was asked
for. `HALOGEN_DMALLOC_LOG=1` prints every allocation over 64 MB with a running
total, which is this configuration's memory budget measured rather than
estimated, and `HALOGEN_VERBOSE=1` turns on the fullest startup account the
server can give. Both are off by default and both are useful to attach to a
report. The two lines worth sending on their own are:

```
docker logs <container> 2>&1 | grep -E '^(dmalloc|kv pool):'
```

## If the load fails on Fedora with "Memory critical error"

Fedora enforces SELinux, and its policy does not let a container map
`/dev/kfd` unless the `container_use_devices` boolean is on, which it is not
by default. A load then fails early with `Memory critical error by agent
node-0 ... Reason: Memory in use`, and `sudo ausearch -m avc -ts recent`
shows `denied { map }` on `/dev/kfd`. Every run line here carries
`--ipc=host`, and Podman runs a container that shares the host's IPC
namespace without SELinux separation (`spc_t` rather than `container_t`),
which is why they work on our Fedora host with the boolean off. If you
leave `--ipc=host` out, turn the boolean on instead:

```
sudo setsebool -P container_use_devices true
```

## The host settings these numbers were measured on

**Native Linux only.** This server runs on the amdgpu/KFD driver stack and
its memory design depends on it: the checkpoint is mapped and registered with
the GPU in place, never copied, and every memory ceiling it knows about lives
in that driver. **WSL2 (ROCm through `/dev/dxg`) is not a supported host**: the
registration is refused there, and the server does not reach readiness. If
you are on that stack, the same hardware booted into Linux is the path that
works.

**A kernel with AMD's gfx1151 fixes, built with KFD's shared virtual memory
support.** The checkpoint is a read-only file mapping registered with the GPU
in place, and the kernel must provide two things. The first is AMD's two
gfx1151 fixes to the KFD driver (the VGPR size in the queue creation check,
and the export of `cwsr_size` and `ctl_stack_size`); AMD's Strix Halo page puts
the floor at Linux 6.18.4, Ubuntu 24.04 HWE `6.17.0-19.19~24.04.2`, or Ubuntu
24.04 OEM `6.14.0-1018`, each or later. The second is `CONFIG_HSA_AMD_SVM`
(which needs `CONFIG_DEVICE_PRIVATE`): ROCm registers a read-only mapping
through KFD's SVM interface, and its fallback always asks for writable pages,
which a read-only file cannot give, so without SVM every read-only
registration fails, whatever its size. Fedora built `6.18.6-200.fc43` without
it ([#37](https://github.com/peonist-ai/halogen-flash-server/issues/37) was
that kernel) and turned it on in `6.18.7-200.fc43`; Ubuntu's kernels have it.
Both can be read without a container, on the KFD node whose
`gfx_target_version` is `110501`
(`/sys/class/kfd/kfd/topology/nodes/<n>/properties`): `capability` has bit
`0x08000000` set when SVM is built in, and the fixes are in when a
`cwsr_size` line exists and equals `ctl_stack_size + (simd_count / 2) * 479232`.
A refused registration names a missing SVM bit. Hosts seen working: Fedora
43's 7.1.8 (the reference host), Ubuntu's 7.0.0, and reports on 6.18.38. An
earlier version of this
page said "7.0 or newer"; that was an inference from #37 alone.

Everything in [Measured](performance.md#measured) was measured on a machine booted like this,
and the same command line has been in place unchanged for the whole life of
this engine. **This is our configuration, not a tuning guide**: of the six
settings we have A/B'd exactly one, and it is published here so the numbers can
be reproduced and so a slow machine has somewhere to look.

```
amdgpu.vm_update_mode=0 amdgpu.noretry=0 amdgpu.gttsize=126976
ttm.pages_limit=32505856 amdgpu.sg_display=0 amd_iommu=off
```

**`amd_iommu=off` is the one we have measured, and it is worth 13 to 16 percent
of prefill.** The numbers and the mechanism are in the conditions paragraph
above. Two things to weigh before copying it: it turns off DMA translation
machine-wide, which is a real change in posture on a host that is not dedicated
to this, and it takes the NPU with it. On a box that exists to serve this model
it is the right trade and it is the one we made.

**`ttm.pages_limit` and `amdgpu.gttsize` are sizes, not constants. Do not paste
ours.** GTT is where every allocation this server makes on the GPU actually
lands, and `ttm.pages_limit` sets that ceiling exactly: 32,505,856 pages times
4 KiB is 124 GiB, which is 99.3% of this machine's RAM, and it is precisely
what the driver then reports as its GTT total. Both values say the same thing
in different units, so set both to about your installed RAM:

| machine | `amdgpu.gttsize` (MiB) | `ttm.pages_limit` (4 KiB pages) |
|---|---|---|
| 128 GB | `126976` | `32505856` |
| 96 GB | `95232` | `24379392` |
| 64 GB | `63488` | `16252928` |

Pasting the 128 GB row onto a 64 GB machine asks the driver for more GTT than
the machine has. **Neither flag is required.** Measured on a second 128 GB
machine on a stock kernel command line: the kernel's default GTT is half of
RAM (60.6 GiB there), this server at the Quickstart defaults uses about
27 GiB of it (the weights are registered host memory and do not count
against GTT), and the Quickstart served from that default without either
flag. Ours are set because we set them on day one, not because the server
needs them.

The remaining three, `amdgpu.vm_update_mode=0`, `amdgpu.noretry=0` and
`amdgpu.sg_display=0`, we have never run without. They are listed for
completeness rather than recommended, and they are unmeasured in both
directions: we make no claim about what they buy. One of them changes a
failure's shape rather than any speed: `amdgpu.noretry=0` makes the GPU
retry a page whose mapping is gone instead of faulting, so an event that
produces `Page not present` on a default boot (issue #83) produces a silent
engine on ours (issue #85). Neither is better; know which one you will see. Two reports
([#34](https://github.com/peonist-ai/halogen-flash-server/issues/34)) of the
driver keeping an engine's GPU memory after the process was gone came from
boots with them set, and one A/B on one machine ran clean without them, so
this section said for a week to leave them off. A third host
([#79](https://github.com/peonist-ai/halogen-flash-server/issues/79)) then
reached the same state with none of the three set, and our own gate machine
reached it once with all of them, so the flags are not what decides it. What
the four share is a process holding the GPU ending while the driver had work
in flight: another model's exit, a bench's normal exit, a cancelled request
on a busy queue, a watchdog kill under a memory stall. After it, 35 to 45
GiB of GTT stays allocated with nothing alive (`Trying to push to a killed
entity` in dmesg on two of them, a kernel worker in `svm_range_restore_work`
in D on two), and every later start either refuses at the pin guard or hangs
at `reserving the KV pool` until the host reboots. Nothing in user space
releases it; `amdgpu_gpu_recover` through debugfs may, and we have not
tried it. Since 0.11.9 the container reads the counters before it starts
and names the state (the troubleshooting section above shows the lines),
and its watchdog no longer kills an engine that is silent inside the
kernel, which is where #79's two kills landed. The flags: leave them
off unless something else needs them, and do not expect that to be what
saves you. After any unclean exit, check

```
cat /sys/class/drm/card*/device/mem_info_gtt_used
```

before starting again; tens of GiB with no container running is the state
above.

Check what you are on with:

```
cat /proc/cmdline
```

**The power profile.** Our numbers were measured at about 85 W of sustained
package power. Some machines expose an ACPI platform profile and ship it at
`balanced`. One owner's machine held about 70 W there and about 127 W under
`performance`, and decoded faster at the higher limit (measured on another
engine). Check with `cat /sys/firmware/acpi/platform_profile` (the choices
are in `platform_profile_choices`). If it reads `balanced` and you want to
compare with the numbers here, set it with
`echo performance | sudo tee /sys/firmware/acpi/platform_profile`. Neither
of our machines exposes the file.

---
