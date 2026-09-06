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

# The subject script is embedded below as base64, so this harness reads
# no file and cannot be pointed at different bytes than the emitter saw.
set daedalus_script_base64 {
IyBEYWVkYWx1cyBlbWl0dGVkIEFNRCBWaXRpcyBITFMgQyBzeW50aGVzaXMgZmxvdy4KIwojIHNj
aGVtYTogICAgIGRhZWRhbHVzLWNoaXAtdGNsLWVtaXQvMQojIHRhcmdldDogICAgIHZpdGlzLWhs
cwojIHNjb3BlOiAgICAgIGNzeW50aAojIGVtaXR0ZXI6ICAgIGRhZWRhbHVzLmNoaXBfZGVzaWdu
LnRjbF9lbWl0CiMgaW52b2NhdGlvbjogdml0aXNfaGxzIC1mIDx0aGlzIGZpbGU+CiMKIyBCb3Vu
ZCBpZGVudGl0aWVzLiBUaGlzIHNjcmlwdCBpcyBhIHBsYW4gZm9yIGV4YWN0bHkgdGhlc2UgaW5w
dXRzOyBpZiBhCiMgZGlnZXN0IGJlbG93IG5vIGxvbmdlciBtYXRjaGVzLCByZS1lbWl0IGluc3Rl
YWQgb2YgZWRpdGluZyB0aGlzIGZpbGUuCiMgICBrZXJuZWxfc2hhMjU2OiA2NjY2NjY2NjY2NjY2
NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2CiMgICBw
bGFuX3NoYTI1NjogICA3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3
Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3CiMKIyBEYWVkYWx1cyBlbWl0dGVkIHRoaXMgdGV4dCBhbmQg
ZGlkIG5vdCBydW4gaXQuIFRoZSBlbWl0dGluZyBjb21tYW5kCiMgc3Bhd25zIG5vIHByb2Nlc3Mu
IEEgcGFzc2luZyBUY2wgY29tcGxldGVuZXNzIGNoZWNrIGlzIG5vdCBldmlkZW5jZQojIHRoYXQg
QU1EIFZpdmFkbyBvciBWaXRpcyBITFMgYWNjZXB0cyB0aGlzIHNjcmlwdCwgYW5kIHRoaXMgZmls
ZSBpcwojIG5laXRoZXIgYSBidWlsZCByZXN1bHQgbm9yIGEgcHJvbW90aW9uLgoKc2V0IGRhZWRh
bHVzX2tlcm5lbCB7QzovcGlubmVkL2tlcm5lbC92YWRkLmNwcH0Kc2V0IGRhZWRhbHVzX3Byb2pl
Y3RfZGlyIHtDOi9waW5uZWQvLmRhZWRhbHVzLWNoaXAvcGxhbnMvaGxzL3ZhZGQvaGxzX3Byb2pl
Y3R9CnNldCBkYWVkYWx1c19vdXRwdXRfZGlyIHtDOi9waW5uZWQvLmRhZWRhbHVzLWNoaXAvcGxh
bnMvaGxzL3ZhZGQvcmVwb3J0c30Kc2V0IGRhZWRhbHVzX3RvcCB7dmFkZH0Kc2V0IGRhZWRhbHVz
X3BhcnQge3hjdTI1MC1maWdkMjEwNC0yTC1lfQpzZXQgZGFlZGFsdXNfc29sdXRpb24ge3NvbHV0
aW9uMX0Kc2V0IGRhZWRhbHVzX2Nsb2NrX3BlcmlvZCAxMApzZXQgZGFlZGFsdXNfa2VybmVsX3No
YTI1NiB7NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2
NjY2NjY2NjY2NjY2Nn0Kc2V0IGRhZWRhbHVzX3BsYW5fc2hhMjU2IHs3Nzc3Nzc3Nzc3Nzc3Nzc3
Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3Nzc3fQoKcHJvYyBk
YWVkYWx1c19mYWlsIHttZXNzYWdlIGNvZGV9IHsKICAgIHB1dHMgc3RkZXJyICJEQUVEQUxVU19W
SVRJU19ITFNfRU1JVFRFRF9FUlJPUiBjb2RlPSRjb2RlIG1lc3NhZ2U9JG1lc3NhZ2UiCiAgICBj
YXRjaCB7Y2xvc2VfZGVzaWdufQogICAgY2F0Y2gge2Nsb3NlX3Byb2plY3R9CiAgICBleGl0ICRj
b2RlCn0KCmlmIHshW2ZpbGUgZXhpc3RzICRkYWVkYWx1c19rZXJuZWxdfSB7CiAgICBkYWVkYWx1
c19mYWlsICJrZXJuZWwgc291cmNlIGlzIG1pc3Npbmc6ICRkYWVkYWx1c19rZXJuZWwiIDMwCn0K
ZmlsZSBta2RpciAkZGFlZGFsdXNfb3V0cHV0X2RpcgoKb3Blbl9wcm9qZWN0IC1yZXNldCAkZGFl
ZGFsdXNfcHJvamVjdF9kaXIKYWRkX2ZpbGVzICRkYWVkYWx1c19rZXJuZWwKc2V0X3RvcCAkZGFl
ZGFsdXNfdG9wCm9wZW5fc29sdXRpb24gLXJlc2V0ICRkYWVkYWx1c19zb2x1dGlvbiAtZmxvd190
YXJnZXQgdml2YWRvCnNldF9wYXJ0ICRkYWVkYWx1c19wYXJ0CmNyZWF0ZV9jbG9jayAtcGVyaW9k
ICRkYWVkYWx1c19jbG9ja19wZXJpb2QgLW5hbWUgZGVmYXVsdApjc3ludGhfZGVzaWduCgpzZXQg
ZGFlZGFsdXNfcmVwb3J0IFtmaWxlIGpvaW4gJGRhZWRhbHVzX3Byb2plY3RfZGlyIFwKICAgICRk
YWVkYWx1c19zb2x1dGlvbiBzeW4gcmVwb3J0ICR7ZGFlZGFsdXNfdG9wfV9jc3ludGgucnB0XQpp
ZiB7IVtmaWxlIGV4aXN0cyAkZGFlZGFsdXNfcmVwb3J0XX0gewogICAgZGFlZGFsdXNfZmFpbCAi
Y3N5bnRoIHJlcG9ydCBpcyBtaXNzaW5nOiAkZGFlZGFsdXNfcmVwb3J0IiAzMQp9CmZpbGUgY29w
eSAtZm9yY2UgJGRhZWRhbHVzX3JlcG9ydCBcCiAgICBbZmlsZSBqb2luICRkYWVkYWx1c19vdXRw
dXRfZGlyIGNzeW50aC5ycHRdCgpzZXQgZGFlZGFsdXNfc3VtbWFyeV9wYXRoIFwKICAgIFtmaWxl
IGpvaW4gJGRhZWRhbHVzX291dHB1dF9kaXIgaGxzX3N1bW1hcnkudHh0XQpzZXQgZGFlZGFsdXNf
c3VtbWFyeSBbb3BlbiAkZGFlZGFsdXNfc3VtbWFyeV9wYXRoIHddCnB1dHMgJGRhZWRhbHVzX3N1
bW1hcnkgInNjaGVtYT1kYWVkYWx1cy1jaGlwLXRjbC1lbWl0LzEiCnB1dHMgJGRhZWRhbHVzX3N1
bW1hcnkgInNjb3BlPWNzeW50aCIKcHV0cyAkZGFlZGFsdXNfc3VtbWFyeSAicGFydD0kZGFlZGFs
dXNfcGFydCIKcHV0cyAkZGFlZGFsdXNfc3VtbWFyeSAidG9wPSRkYWVkYWx1c190b3AiCnB1dHMg
JGRhZWRhbHVzX3N1bW1hcnkgInNvbHV0aW9uPSRkYWVkYWx1c19zb2x1dGlvbiIKcHV0cyAkZGFl
ZGFsdXNfc3VtbWFyeSAiY2xvY2tfcGVyaW9kPSRkYWVkYWx1c19jbG9ja19wZXJpb2QiCnB1dHMg
JGRhZWRhbHVzX3N1bW1hcnkgImtlcm5lbF9zaGEyNTY9JGRhZWRhbHVzX2tlcm5lbF9zaGEyNTYi
CnB1dHMgJGRhZWRhbHVzX3N1bW1hcnkgInBsYW5fc2hhMjU2PSRkYWVkYWx1c19wbGFuX3NoYTI1
NiIKY2xvc2UgJGRhZWRhbHVzX3N1bW1hcnkKCmNsb3NlX3Byb2plY3QKcHV0cyAiREFFREFMVVNf
VklUSVNfSExTX0VNSVRURURfT0sgc2NvcGU9Y3N5bnRoIgpleGl0IDAK
}
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

set daedalus_body [binary decode base64 $daedalus_script_base64]
set daedalus_complete [info complete $daedalus_body]

set daedalus_exit_code {}
set daedalus_error {}
if {[catch {eval $daedalus_body} daedalus_result daedalus_options]} {
    set daedalus_code [dict get $daedalus_options -errorcode]
    if {[lindex $daedalus_code 0] ne "DAEDALUS"} {
        set daedalus_error $daedalus_result
    }
}

puts "DAEDALUS_TCL_PARSE sha256_expected=$daedalus_expected_sha256"
puts "DAEDALUS_TCL_PARSE embedded_bytes=[string length $daedalus_body]"
puts "DAEDALUS_TCL_PARSE complete=$daedalus_complete"
puts "DAEDALUS_TCL_PARSE stub_calls=[llength $daedalus_calls]"
puts "DAEDALUS_TCL_PARSE intercepted_exit=$daedalus_exit_code"
puts "DAEDALUS_TCL_PARSE tcl_error=$daedalus_error"
puts "DAEDALUS_TCL_PARSE vendor_acceptance_claimed=0"
if {!$daedalus_complete || $daedalus_error ne ""} {
    daedalus_real_exit 1
}
daedalus_real_exit 0
