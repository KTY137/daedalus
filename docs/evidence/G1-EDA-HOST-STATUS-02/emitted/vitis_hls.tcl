# Daedalus emitted AMD Vitis HLS C synthesis flow.
#
# schema:     daedalus-chip-tcl-emit/1
# target:     vitis-hls
# scope:      csynth
# emitter:    daedalus.chip_design.tcl_emit
# invocation: vitis_hls -f <this file>
#
# Bound identities. This script is a plan for exactly these inputs; if a
# digest below no longer matches, re-emit instead of editing this file.
#   kernel_sha256: 6666666666666666666666666666666666666666666666666666666666666666
#   plan_sha256:   7777777777777777777777777777777777777777777777777777777777777777
#
# Daedalus emitted this text and did not run it. The emitting command
# spawns no process. A passing Tcl completeness check is not evidence
# that AMD Vivado or Vitis HLS accepts this script, and this file is
# neither a build result nor a promotion.

set daedalus_kernel {C:/pinned/kernel/vadd.cpp}
set daedalus_project_dir {C:/pinned/.daedalus-chip/plans/hls/vadd/hls_project}
set daedalus_output_dir {C:/pinned/.daedalus-chip/plans/hls/vadd/reports}
set daedalus_top {vadd}
set daedalus_part {xcu250-figd2104-2L-e}
set daedalus_solution {solution1}
set daedalus_clock_period 10
set daedalus_kernel_sha256 {6666666666666666666666666666666666666666666666666666666666666666}
set daedalus_plan_sha256 {7777777777777777777777777777777777777777777777777777777777777777}

proc daedalus_fail {message code} {
    puts stderr "DAEDALUS_VITIS_HLS_EMITTED_ERROR code=$code message=$message"
    catch {close_design}
    catch {close_project}
    exit $code
}

if {![file exists $daedalus_kernel]} {
    daedalus_fail "kernel source is missing: $daedalus_kernel" 30
}
file mkdir $daedalus_output_dir

open_project -reset $daedalus_project_dir
add_files $daedalus_kernel
set_top $daedalus_top
open_solution -reset $daedalus_solution -flow_target vivado
set_part $daedalus_part
create_clock -period $daedalus_clock_period -name default
csynth_design

set daedalus_report [file join $daedalus_project_dir \
    $daedalus_solution syn report ${daedalus_top}_csynth.rpt]
if {![file exists $daedalus_report]} {
    daedalus_fail "csynth report is missing: $daedalus_report" 31
}
file copy -force $daedalus_report \
    [file join $daedalus_output_dir csynth.rpt]

set daedalus_summary_path \
    [file join $daedalus_output_dir hls_summary.txt]
set daedalus_summary [open $daedalus_summary_path w]
puts $daedalus_summary "schema=daedalus-chip-tcl-emit/1"
puts $daedalus_summary "scope=csynth"
puts $daedalus_summary "part=$daedalus_part"
puts $daedalus_summary "top=$daedalus_top"
puts $daedalus_summary "solution=$daedalus_solution"
puts $daedalus_summary "clock_period=$daedalus_clock_period"
puts $daedalus_summary "kernel_sha256=$daedalus_kernel_sha256"
puts $daedalus_summary "plan_sha256=$daedalus_plan_sha256"
close $daedalus_summary

close_project
puts "DAEDALUS_VITIS_HLS_EMITTED_OK scope=csynth"
exit 0
