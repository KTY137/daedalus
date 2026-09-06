# Daedalus emitted AMD Vivado project flow.
#
# schema:     daedalus-chip-tcl-emit/1
# target:     vivado-project
# scope:      full
# emitter:    daedalus.chip_design.tcl_emit
# invocation: vivado -mode batch -nojournal -nolog -notrace -source <this file>
#
# Bound identities. This script is a plan for exactly these inputs; if a
# digest below no longer matches, re-emit instead of editing this file.
#   project_sha256:         1111111111111111111111111111111111111111111111111111111111111111
#   manifest_sha256:        2222222222222222222222222222222222222222222222222222222222222222
#   source_identity_sha256: 3333333333333333333333333333333333333333333333333333333333333333
#   plan_sha256:            4444444444444444444444444444444444444444444444444444444444444444
#   trusted_tcl_sha256:     5555555555555555555555555555555555555555555555555555555555555555
#
# Daedalus emitted this text and did not run it. The emitting command
# spawns no process. A passing Tcl completeness check is not evidence
# that AMD Vivado or Vitis HLS accepts this script, and this file is
# neither a build result nor a promotion.

set daedalus_project_file {C:/pinned/demo.xpr}
set daedalus_project_root {C:/pinned}
set daedalus_output_dir {C:/pinned/.daedalus-chip/plans/emitted/full}
set daedalus_part {xc7a35ticsg324-1L}
set daedalus_board_part {}
set daedalus_top {top}
set daedalus_synth_run {synth_1}
set daedalus_impl_run {impl_1}
set daedalus_jobs 1
set daedalus_project_sha256 {1111111111111111111111111111111111111111111111111111111111111111}
set daedalus_plan_sha256 {4444444444444444444444444444444444444444444444444444444444444444}

set daedalus_design_sources [list \
    {demo.srcs/sources_1/new/top.sv} \
]
set daedalus_constraint_sources [list \
    {demo.srcs/constrs_1/new/pins.xdc} \
]

proc daedalus_fail {message code} {
    puts stderr "DAEDALUS_VIVADO_EMITTED_ERROR code=$code message=$message"
    catch {close_design}
    catch {close_project}
    exit $code
}

proc daedalus_expect {label actual expected} {
    if {$actual ne $expected} {
        daedalus_fail "$label is $actual, expected $expected" 20
    }
}

proc daedalus_require_complete_run {run label} {
    set progress [get_property PROGRESS [get_runs $run]]
    set status [get_property STATUS [get_runs $run]]
    if {$progress ne "100%"} {
        daedalus_fail "$label stopped at $progress: $status" 21
    }
}

file mkdir $daedalus_output_dir

if {[file exists $daedalus_project_file]} {
    open_project $daedalus_project_file
} else {
    create_project -force -part $daedalus_part \
        [file rootname [file tail $daedalus_project_file]] \
        [file dirname $daedalus_project_file]
    foreach daedalus_source $daedalus_design_sources {
        add_files -norecurse \
            [file join $daedalus_project_root $daedalus_source]
    }
    foreach daedalus_constraint $daedalus_constraint_sources {
        add_files -fileset constrs_1 -norecurse \
            [file join $daedalus_project_root $daedalus_constraint]
    }
    set_property top $daedalus_top [current_fileset]
}

daedalus_expect "project part" \
    [get_property PART [current_project]] $daedalus_part
daedalus_expect "top module" \
    [get_property TOP [current_fileset]] $daedalus_top
if {$daedalus_board_part ne ""} {
    daedalus_expect "board part" \
        [get_property BOARD_PART [current_project]] $daedalus_board_part
}

reset_run $daedalus_synth_run
launch_runs $daedalus_synth_run -jobs $daedalus_jobs
wait_on_run $daedalus_synth_run
daedalus_require_complete_run $daedalus_synth_run "synthesis"
open_run $daedalus_synth_run -name $daedalus_synth_run
write_checkpoint -force \
    [file join $daedalus_output_dir synth_design.dcp]
report_utilization -file \
    [file join $daedalus_output_dir utilization.rpt]
report_timing_summary -file \
    [file join $daedalus_output_dir timing_summary.rpt]
report_drc -file [file join $daedalus_output_dir drc.rpt]
report_methodology -file \
    [file join $daedalus_output_dir methodology.rpt]
close_design

reset_run $daedalus_impl_run
launch_runs $daedalus_impl_run -jobs $daedalus_jobs
wait_on_run $daedalus_impl_run
daedalus_require_complete_run $daedalus_impl_run "implementation"
open_run $daedalus_impl_run
write_checkpoint -force [file join $daedalus_output_dir design.dcp]
report_utilization -file \
    [file join $daedalus_output_dir utilization.rpt]
report_timing_summary -file \
    [file join $daedalus_output_dir timing_summary.rpt]
report_drc -file [file join $daedalus_output_dir drc.rpt]
report_methodology -file \
    [file join $daedalus_output_dir methodology.rpt]
report_route_status -file \
    [file join $daedalus_output_dir route_status.rpt]
write_bitstream -force [file join $daedalus_output_dir design.bit]
if {![file exists [file join $daedalus_output_dir design.bit]]} {
    daedalus_fail "bitstream was not written" 22
}
close_design

set daedalus_summary_path [file join $daedalus_output_dir impl_summary.txt]
set daedalus_summary [open $daedalus_summary_path w]
puts $daedalus_summary "schema=daedalus-chip-tcl-emit/1"
puts $daedalus_summary "scope=full"
puts $daedalus_summary "part=$daedalus_part"
puts $daedalus_summary "top=$daedalus_top"
puts $daedalus_summary "project_sha256=$daedalus_project_sha256"
puts $daedalus_summary "plan_sha256=$daedalus_plan_sha256"
puts $daedalus_summary "synth_progress=[get_property PROGRESS [get_runs $daedalus_synth_run]]"
puts $daedalus_summary "impl_progress=[get_property PROGRESS [get_runs $daedalus_impl_run]]"
close $daedalus_summary

close_project
puts "DAEDALUS_VIVADO_EMITTED_OK scope=full"
exit 0
