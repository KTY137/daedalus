# Daedalus emitted Tcl parse harness (no vendor command runs).
#
# schema:     daedalus-chip-tcl-emit/1
# target:     parse-harness
# scope:      csynth
# emitter:    daedalus.chip_design.tcl_emit
# invocation: tclsh <this file>
#
# Bound identities. This script is a plan for exactly these inputs; if a
# digest below no longer matches, re-emit instead of editing this file.
#   script_sha256: 80ef3c3ceae3247cb861f07a3b42a2c168fbb5ceedfeb457735d4118f41cd4ed
#   script_target: vitis-hls
#   script_scope:  csynth
#
# Daedalus emitted this text and did not run it. The emitting command
# spawns no process. A passing Tcl completeness check is not evidence
# that AMD Vivado or Vitis HLS accepts this script, and this file is
# neither a build result nor a promotion.

set daedalus_script {C:/pinned/out/vitis_hls.tcl}
set daedalus_expected_sha256 {80ef3c3ceae3247cb861f07a3b42a2c168fbb5ceedfeb457735d4118f41cd4ed}
set daedalus_calls [list]

proc daedalus_record {name args} {
    global daedalus_calls
    lappend daedalus_calls $name
    return ""
}

foreach daedalus_command [list \
    add_files \
    close_project \
    create_clock \
    csynth_design \
    open_project \
    open_solution \
    set_part \
    set_top \
] {
    proc $daedalus_command {args} \
        "daedalus_record [list $daedalus_command]"
}

# Vendor property reads answer with the value the emitted script expects,
# so the parse walks the success path instead of stopping at check one.
proc get_property {property args} {
    daedalus_record get_property
    set key [string toupper $property]
    if {$key eq "PART" && [info exists ::daedalus_part]} {
        return $::daedalus_part
    }
    if {$key eq "TOP" && [info exists ::daedalus_top]} {
        return $::daedalus_top
    }
    if {$key eq "BOARD_PART" && [info exists ::daedalus_board_part]} {
        return $::daedalus_board_part
    }
    if {$key eq "PROGRESS"} {
        return "100%"
    }
    if {$key eq "STATUS"} {
        return "daedalus-stub-complete"
    }
    return ""
}

# Effectful Tcl surfaces are replaced so the harness writes nothing.
rename file daedalus_real_file
proc file {args} {
    set subcommand [lindex $args 0]
    switch -- $subcommand {
        mkdir - copy - delete - rename {
            daedalus_record file_$subcommand
            return ""
        }
        exists {
            return 1
        }
        default {
            return [daedalus_real_file {*}$args]
        }
    }
}

rename open daedalus_real_open
proc open {args} {
    daedalus_record open
    if {$::tcl_platform(platform) eq "windows"} {
        return [daedalus_real_open NUL w]
    }
    return [daedalus_real_open /dev/null w]
}

rename exit daedalus_real_exit
proc exit {{code 0}} {
    global daedalus_exit_code
    set daedalus_exit_code $code
    return -code error -errorcode {DAEDALUS EXIT} \
        "daedalus-intercepted-exit"
}

set daedalus_channel [daedalus_real_open $daedalus_script r]
fconfigure $daedalus_channel -translation binary
set daedalus_body [read $daedalus_channel]
close $daedalus_channel
set daedalus_complete [info complete $daedalus_body]

set daedalus_exit_code {}
set daedalus_error {}
if {[catch {eval $daedalus_body} daedalus_result daedalus_options]} {
    set daedalus_code [dict get $daedalus_options -errorcode]
    if {[lindex $daedalus_code 0] ne "DAEDALUS"} {
        set daedalus_error $daedalus_result
    }
}

puts "DAEDALUS_TCL_PARSE script=$daedalus_script"
puts "DAEDALUS_TCL_PARSE sha256_expected=$daedalus_expected_sha256"
puts "DAEDALUS_TCL_PARSE complete=$daedalus_complete"
puts "DAEDALUS_TCL_PARSE stub_calls=[llength $daedalus_calls]"
puts "DAEDALUS_TCL_PARSE intercepted_exit=$daedalus_exit_code"
puts "DAEDALUS_TCL_PARSE tcl_error=$daedalus_error"
puts "DAEDALUS_TCL_PARSE vendor_acceptance_claimed=0"
if {!$daedalus_complete || $daedalus_error ne ""} {
    daedalus_real_exit 1
}
daedalus_real_exit 0
