# Daedalus emitted Tcl parse harness (no vendor command runs).
#
# schema:     daedalus-chip-tcl-emit/1
# target:     parse-harness
# scope:      full
# emitter:    daedalus.chip_design.tcl_emit
# invocation: tclsh <this file>
#
# Bound identities. This script is a plan for exactly these inputs; if a
# digest below no longer matches, re-emit instead of editing this file.
#   script_sha256: 99e3fc661fcd90b4f51578af81078f84ec8b149ae025333e291673c19305d964
#   script_target: vivado-project
#   script_scope:  full
#
# Daedalus emitted this text and did not run it. The emitting command
# spawns no process. A passing Tcl completeness check is not evidence
# that AMD Vivado or Vitis HLS accepts this script, and this file is
# neither a build result nor a promotion.

# The subject script is embedded below as base64, so this harness reads
# no file and cannot be pointed at different bytes than the emitter saw.
set daedalus_script_base64 {
IyBEYWVkYWx1cyBlbWl0dGVkIEFNRCBWaXZhZG8gcHJvamVjdCBmbG93LgojCiMgc2NoZW1hOiAg
ICAgZGFlZGFsdXMtY2hpcC10Y2wtZW1pdC8xCiMgdGFyZ2V0OiAgICAgdml2YWRvLXByb2plY3QK
IyBzY29wZTogICAgICBmdWxsCiMgZW1pdHRlcjogICAgZGFlZGFsdXMuY2hpcF9kZXNpZ24udGNs
X2VtaXQKIyBpbnZvY2F0aW9uOiB2aXZhZG8gLW1vZGUgYmF0Y2ggLW5vam91cm5hbCAtbm9sb2cg
LW5vdHJhY2UgLXNvdXJjZSA8dGhpcyBmaWxlPgojCiMgQm91bmQgaWRlbnRpdGllcy4gVGhpcyBz
Y3JpcHQgaXMgYSBwbGFuIGZvciBleGFjdGx5IHRoZXNlIGlucHV0czsgaWYgYQojIGRpZ2VzdCBi
ZWxvdyBubyBsb25nZXIgbWF0Y2hlcywgcmUtZW1pdCBpbnN0ZWFkIG9mIGVkaXRpbmcgdGhpcyBm
aWxlLgojICAgcHJvamVjdF9zaGEyNTY6ICAgICAgICAgMTExMTExMTExMTExMTExMTExMTExMTEx
MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMQojICAgbWFuaWZlc3Rfc2hh
MjU2OiAgICAgICAgMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy
MjIyMjIyMjIyMjIyMjIyMjIyMgojICAgc291cmNlX2lkZW50aXR5X3NoYTI1NjogMzMzMzMzMzMz
MzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMwoj
ICAgcGxhbl9zaGEyNTY6ICAgICAgICAgICAgNDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0
NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NAojICAgdHJ1c3RlZF90Y2xfc2hhMjU2
OiAgICAgNTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1
NTU1NTU1NTU1NTU1NQojCiMgRGFlZGFsdXMgZW1pdHRlZCB0aGlzIHRleHQgYW5kIGRpZCBub3Qg
cnVuIGl0LiBUaGUgZW1pdHRpbmcgY29tbWFuZAojIHNwYXducyBubyBwcm9jZXNzLiBBIHBhc3Np
bmcgVGNsIGNvbXBsZXRlbmVzcyBjaGVjayBpcyBub3QgZXZpZGVuY2UKIyB0aGF0IEFNRCBWaXZh
ZG8gb3IgVml0aXMgSExTIGFjY2VwdHMgdGhpcyBzY3JpcHQsIGFuZCB0aGlzIGZpbGUgaXMKIyBu
ZWl0aGVyIGEgYnVpbGQgcmVzdWx0IG5vciBhIHByb21vdGlvbi4KCnNldCBkYWVkYWx1c19wcm9q
ZWN0X2ZpbGUge0M6L3Bpbm5lZC9kZW1vLnhwcn0Kc2V0IGRhZWRhbHVzX3Byb2plY3Rfcm9vdCB7
QzovcGlubmVkfQpzZXQgZGFlZGFsdXNfb3V0cHV0X2RpciB7QzovcGlubmVkLy5kYWVkYWx1cy1j
aGlwL3BsYW5zL2VtaXR0ZWQvZnVsbH0Kc2V0IGRhZWRhbHVzX3BhcnQge3hjN2EzNXRpY3NnMzI0
LTFMfQpzZXQgZGFlZGFsdXNfYm9hcmRfcGFydCB7fQpzZXQgZGFlZGFsdXNfdG9wIHt0b3B9CnNl
dCBkYWVkYWx1c19zeW50aF9ydW4ge3N5bnRoXzF9CnNldCBkYWVkYWx1c19pbXBsX3J1biB7aW1w
bF8xfQpzZXQgZGFlZGFsdXNfam9icyAxCnNldCBkYWVkYWx1c19wcm9qZWN0X3NoYTI1NiB7MTEx
MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTEx
MTExMX0Kc2V0IGRhZWRhbHVzX3BsYW5fc2hhMjU2IHs0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0
NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0fQoKc2V0IGRhZWRhbHVzX2Rl
c2lnbl9zb3VyY2VzIFtsaXN0IFwKICAgIHtkZW1vLnNyY3Mvc291cmNlc18xL25ldy90b3Auc3Z9
IFwKXQpzZXQgZGFlZGFsdXNfY29uc3RyYWludF9zb3VyY2VzIFtsaXN0IFwKICAgIHtkZW1vLnNy
Y3MvY29uc3Ryc18xL25ldy9waW5zLnhkY30gXApdCgpwcm9jIGRhZWRhbHVzX2ZhaWwge21lc3Nh
Z2UgY29kZX0gewogICAgcHV0cyBzdGRlcnIgIkRBRURBTFVTX1ZJVkFET19FTUlUVEVEX0VSUk9S
IGNvZGU9JGNvZGUgbWVzc2FnZT0kbWVzc2FnZSIKICAgIGNhdGNoIHtjbG9zZV9kZXNpZ259CiAg
ICBjYXRjaCB7Y2xvc2VfcHJvamVjdH0KICAgIGV4aXQgJGNvZGUKfQoKcHJvYyBkYWVkYWx1c19l
eHBlY3Qge2xhYmVsIGFjdHVhbCBleHBlY3RlZH0gewogICAgaWYgeyRhY3R1YWwgbmUgJGV4cGVj
dGVkfSB7CiAgICAgICAgZGFlZGFsdXNfZmFpbCAiJGxhYmVsIGlzICRhY3R1YWwsIGV4cGVjdGVk
ICRleHBlY3RlZCIgMjAKICAgIH0KfQoKcHJvYyBkYWVkYWx1c19yZXF1aXJlX2NvbXBsZXRlX3J1
biB7cnVuIGxhYmVsfSB7CiAgICBzZXQgcHJvZ3Jlc3MgW2dldF9wcm9wZXJ0eSBQUk9HUkVTUyBb
Z2V0X3J1bnMgJHJ1bl1dCiAgICBzZXQgc3RhdHVzIFtnZXRfcHJvcGVydHkgU1RBVFVTIFtnZXRf
cnVucyAkcnVuXV0KICAgIGlmIHskcHJvZ3Jlc3MgbmUgIjEwMCUifSB7CiAgICAgICAgZGFlZGFs
dXNfZmFpbCAiJGxhYmVsIHN0b3BwZWQgYXQgJHByb2dyZXNzOiAkc3RhdHVzIiAyMQogICAgfQp9
CgpmaWxlIG1rZGlyICRkYWVkYWx1c19vdXRwdXRfZGlyCgppZiB7W2ZpbGUgZXhpc3RzICRkYWVk
YWx1c19wcm9qZWN0X2ZpbGVdfSB7CiAgICBvcGVuX3Byb2plY3QgJGRhZWRhbHVzX3Byb2plY3Rf
ZmlsZQp9IGVsc2UgewogICAgY3JlYXRlX3Byb2plY3QgLWZvcmNlIC1wYXJ0ICRkYWVkYWx1c19w
YXJ0IFwKICAgICAgICBbZmlsZSByb290bmFtZSBbZmlsZSB0YWlsICRkYWVkYWx1c19wcm9qZWN0
X2ZpbGVdXSBcCiAgICAgICAgW2ZpbGUgZGlybmFtZSAkZGFlZGFsdXNfcHJvamVjdF9maWxlXQog
ICAgZm9yZWFjaCBkYWVkYWx1c19zb3VyY2UgJGRhZWRhbHVzX2Rlc2lnbl9zb3VyY2VzIHsKICAg
ICAgICBhZGRfZmlsZXMgLW5vcmVjdXJzZSBcCiAgICAgICAgICAgIFtmaWxlIGpvaW4gJGRhZWRh
bHVzX3Byb2plY3Rfcm9vdCAkZGFlZGFsdXNfc291cmNlXQogICAgfQogICAgZm9yZWFjaCBkYWVk
YWx1c19jb25zdHJhaW50ICRkYWVkYWx1c19jb25zdHJhaW50X3NvdXJjZXMgewogICAgICAgIGFk
ZF9maWxlcyAtZmlsZXNldCBjb25zdHJzXzEgLW5vcmVjdXJzZSBcCiAgICAgICAgICAgIFtmaWxl
IGpvaW4gJGRhZWRhbHVzX3Byb2plY3Rfcm9vdCAkZGFlZGFsdXNfY29uc3RyYWludF0KICAgIH0K
ICAgIHNldF9wcm9wZXJ0eSB0b3AgJGRhZWRhbHVzX3RvcCBbY3VycmVudF9maWxlc2V0XQp9Cgpk
YWVkYWx1c19leHBlY3QgInByb2plY3QgcGFydCIgXAogICAgW2dldF9wcm9wZXJ0eSBQQVJUIFtj
dXJyZW50X3Byb2plY3RdXSAkZGFlZGFsdXNfcGFydApkYWVkYWx1c19leHBlY3QgInRvcCBtb2R1
bGUiIFwKICAgIFtnZXRfcHJvcGVydHkgVE9QIFtjdXJyZW50X2ZpbGVzZXRdXSAkZGFlZGFsdXNf
dG9wCmlmIHskZGFlZGFsdXNfYm9hcmRfcGFydCBuZSAiIn0gewogICAgZGFlZGFsdXNfZXhwZWN0
ICJib2FyZCBwYXJ0IiBcCiAgICAgICAgW2dldF9wcm9wZXJ0eSBCT0FSRF9QQVJUIFtjdXJyZW50
X3Byb2plY3RdXSAkZGFlZGFsdXNfYm9hcmRfcGFydAp9CgpyZXNldF9ydW4gJGRhZWRhbHVzX3N5
bnRoX3J1bgpsYXVuY2hfcnVucyAkZGFlZGFsdXNfc3ludGhfcnVuIC1qb2JzICRkYWVkYWx1c19q
b2JzCndhaXRfb25fcnVuICRkYWVkYWx1c19zeW50aF9ydW4KZGFlZGFsdXNfcmVxdWlyZV9jb21w
bGV0ZV9ydW4gJGRhZWRhbHVzX3N5bnRoX3J1biAic3ludGhlc2lzIgpvcGVuX3J1biAkZGFlZGFs
dXNfc3ludGhfcnVuIC1uYW1lICRkYWVkYWx1c19zeW50aF9ydW4Kd3JpdGVfY2hlY2twb2ludCAt
Zm9yY2UgXAogICAgW2ZpbGUgam9pbiAkZGFlZGFsdXNfb3V0cHV0X2RpciBzeW50aF9kZXNpZ24u
ZGNwXQpyZXBvcnRfdXRpbGl6YXRpb24gLWZpbGUgXAogICAgW2ZpbGUgam9pbiAkZGFlZGFsdXNf
b3V0cHV0X2RpciB1dGlsaXphdGlvbi5ycHRdCnJlcG9ydF90aW1pbmdfc3VtbWFyeSAtZmlsZSBc
CiAgICBbZmlsZSBqb2luICRkYWVkYWx1c19vdXRwdXRfZGlyIHRpbWluZ19zdW1tYXJ5LnJwdF0K
cmVwb3J0X2RyYyAtZmlsZSBbZmlsZSBqb2luICRkYWVkYWx1c19vdXRwdXRfZGlyIGRyYy5ycHRd
CnJlcG9ydF9tZXRob2RvbG9neSAtZmlsZSBcCiAgICBbZmlsZSBqb2luICRkYWVkYWx1c19vdXRw
dXRfZGlyIG1ldGhvZG9sb2d5LnJwdF0KY2xvc2VfZGVzaWduCgpyZXNldF9ydW4gJGRhZWRhbHVz
X2ltcGxfcnVuCmxhdW5jaF9ydW5zICRkYWVkYWx1c19pbXBsX3J1biAtam9icyAkZGFlZGFsdXNf
am9icwp3YWl0X29uX3J1biAkZGFlZGFsdXNfaW1wbF9ydW4KZGFlZGFsdXNfcmVxdWlyZV9jb21w
bGV0ZV9ydW4gJGRhZWRhbHVzX2ltcGxfcnVuICJpbXBsZW1lbnRhdGlvbiIKb3Blbl9ydW4gJGRh
ZWRhbHVzX2ltcGxfcnVuCndyaXRlX2NoZWNrcG9pbnQgLWZvcmNlIFtmaWxlIGpvaW4gJGRhZWRh
bHVzX291dHB1dF9kaXIgZGVzaWduLmRjcF0KcmVwb3J0X3V0aWxpemF0aW9uIC1maWxlIFwKICAg
IFtmaWxlIGpvaW4gJGRhZWRhbHVzX291dHB1dF9kaXIgdXRpbGl6YXRpb24ucnB0XQpyZXBvcnRf
dGltaW5nX3N1bW1hcnkgLWZpbGUgXAogICAgW2ZpbGUgam9pbiAkZGFlZGFsdXNfb3V0cHV0X2Rp
ciB0aW1pbmdfc3VtbWFyeS5ycHRdCnJlcG9ydF9kcmMgLWZpbGUgW2ZpbGUgam9pbiAkZGFlZGFs
dXNfb3V0cHV0X2RpciBkcmMucnB0XQpyZXBvcnRfbWV0aG9kb2xvZ3kgLWZpbGUgXAogICAgW2Zp
bGUgam9pbiAkZGFlZGFsdXNfb3V0cHV0X2RpciBtZXRob2RvbG9neS5ycHRdCnJlcG9ydF9yb3V0
ZV9zdGF0dXMgLWZpbGUgXAogICAgW2ZpbGUgam9pbiAkZGFlZGFsdXNfb3V0cHV0X2RpciByb3V0
ZV9zdGF0dXMucnB0XQp3cml0ZV9iaXRzdHJlYW0gLWZvcmNlIFtmaWxlIGpvaW4gJGRhZWRhbHVz
X291dHB1dF9kaXIgZGVzaWduLmJpdF0KaWYgeyFbZmlsZSBleGlzdHMgW2ZpbGUgam9pbiAkZGFl
ZGFsdXNfb3V0cHV0X2RpciBkZXNpZ24uYml0XV19IHsKICAgIGRhZWRhbHVzX2ZhaWwgImJpdHN0
cmVhbSB3YXMgbm90IHdyaXR0ZW4iIDIyCn0KY2xvc2VfZGVzaWduCgpzZXQgZGFlZGFsdXNfc3Vt
bWFyeV9wYXRoIFtmaWxlIGpvaW4gJGRhZWRhbHVzX291dHB1dF9kaXIgaW1wbF9zdW1tYXJ5LnR4
dF0Kc2V0IGRhZWRhbHVzX3N1bW1hcnkgW29wZW4gJGRhZWRhbHVzX3N1bW1hcnlfcGF0aCB3XQpw
dXRzICRkYWVkYWx1c19zdW1tYXJ5ICJzY2hlbWE9ZGFlZGFsdXMtY2hpcC10Y2wtZW1pdC8xIgpw
dXRzICRkYWVkYWx1c19zdW1tYXJ5ICJzY29wZT1mdWxsIgpwdXRzICRkYWVkYWx1c19zdW1tYXJ5
ICJwYXJ0PSRkYWVkYWx1c19wYXJ0IgpwdXRzICRkYWVkYWx1c19zdW1tYXJ5ICJ0b3A9JGRhZWRh
bHVzX3RvcCIKcHV0cyAkZGFlZGFsdXNfc3VtbWFyeSAicHJvamVjdF9zaGEyNTY9JGRhZWRhbHVz
X3Byb2plY3Rfc2hhMjU2IgpwdXRzICRkYWVkYWx1c19zdW1tYXJ5ICJwbGFuX3NoYTI1Nj0kZGFl
ZGFsdXNfcGxhbl9zaGEyNTYiCnB1dHMgJGRhZWRhbHVzX3N1bW1hcnkgInN5bnRoX3Byb2dyZXNz
PVtnZXRfcHJvcGVydHkgUFJPR1JFU1MgW2dldF9ydW5zICRkYWVkYWx1c19zeW50aF9ydW5dXSIK
cHV0cyAkZGFlZGFsdXNfc3VtbWFyeSAiaW1wbF9wcm9ncmVzcz1bZ2V0X3Byb3BlcnR5IFBST0dS
RVNTIFtnZXRfcnVucyAkZGFlZGFsdXNfaW1wbF9ydW5dXSIKY2xvc2UgJGRhZWRhbHVzX3N1bW1h
cnkKCmNsb3NlX3Byb2plY3QKcHV0cyAiREFFREFMVVNfVklWQURPX0VNSVRURURfT0sgc2NvcGU9
ZnVsbCIKZXhpdCAwCg==
}
set daedalus_expected_sha256 {99e3fc661fcd90b4f51578af81078f84ec8b149ae025333e291673c19305d964}
set daedalus_calls [list]

proc daedalus_record {name args} {
    global daedalus_calls
    lappend daedalus_calls $name
    return ""
}

foreach daedalus_command [list \
    add_files \
    close_design \
    close_project \
    create_project \
    current_fileset \
    current_project \
    get_runs \
    launch_runs \
    open_project \
    open_run \
    report_drc \
    report_methodology \
    report_route_status \
    report_timing_summary \
    report_utilization \
    reset_run \
    set_property \
    wait_on_run \
    write_bitstream \
    write_checkpoint \
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
