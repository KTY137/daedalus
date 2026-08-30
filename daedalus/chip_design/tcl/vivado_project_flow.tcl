# Daedalus-owned AMD Vivado project flow.
#
# This file is static package data.  Every run-specific value arrives through
# -tclargs; no project-provided automation Tcl or serialized run hook is
# executed directly.  Declared XDC constraint Tcl remains an executable design
# input and is admitted only with its bound Vivado file metadata.

proc daedalus_fail {message code} {
    puts stderr "DAEDALUS_VIVADO_ERROR code=$code message=$message"
    catch {close_design}
    catch {close_project}
    exit $code
}

proc daedalus_normalize {path_value} {
    return [string map {\\ /} [file normalize $path_value]]
}

proc daedalus_path_key {path_value} {
    set normalized [daedalus_normalize $path_value]
    if {$::tcl_platform(platform) eq "windows"} {
        return [string tolower $normalized]
    }
    return $normalized
}

proc daedalus_is_within {root_value child_value} {
    set root_key [string trimright [daedalus_path_key $root_value] /]
    set child_key [daedalus_path_key $child_value]
    if {$child_key eq $root_key} {
        return 1
    }
    set prefix "${root_key}/"
    set prefix_length [string length $prefix]
    return [expr {[string range $child_key 0 [expr {$prefix_length - 1}]] eq $prefix}]
}

proc daedalus_require_run {run_name label} {
    set matches [get_runs -quiet $run_name]
    if {[llength $matches] != 1 || [lindex $matches 0] ne $run_name} {
        daedalus_fail "$label is not one exact run: $run_name" 14
    }
    return [lindex $matches 0]
}

proc daedalus_require_run_property {run candidates label} {
    set properties [list_property $run]
    foreach candidate $candidates {
        set index [lsearch -exact -nocase $properties $candidate]
        if {$index < 0} {
            continue
        }
        set property_name [lindex $properties $index]
        if {[catch {get_property $property_name $run} value]} {
            daedalus_fail "cannot read $label $property_name on $run: $value" 90
        }
        return $value
    }
    daedalus_fail "$label property is unavailable on $run" 90
}

proc daedalus_validate_selected_runs {synth_run impl_run primary_source_set_name expected_part} {
    set synth_is_synthesis [daedalus_require_run_property $synth_run {IS_SYNTHESIS} synthesis-kind]
    set impl_is_synthesis [daedalus_require_run_property $impl_run {IS_SYNTHESIS} implementation-kind]
    set impl_is_implementation [daedalus_require_run_property $impl_run {IS_IMPLEMENTATION} implementation-kind]
    if {!$synth_is_synthesis || $impl_is_synthesis || !$impl_is_implementation} {
        daedalus_fail "selected Vivado runs have swapped or unsupported kinds" 91
    }
    set synth_source_set [daedalus_require_run_property $synth_run {SRCSET} source-set]
    if {$synth_source_set ne $primary_source_set_name} {
        daedalus_fail "selected synthesis run does not use the primary source set" 92
    }
    set synth_part [daedalus_require_run_property $synth_run {PART} part]
    set impl_part [daedalus_require_run_property $impl_run {PART} part]
    if {$synth_part ne $expected_part || $impl_part ne $expected_part} {
        daedalus_fail "selected Vivado run part differs from the project part" 93
    }
    set synth_constraints [daedalus_require_run_property $synth_run {CONSTRSET} constraint-set]
    set impl_constraints [daedalus_require_run_property $impl_run {CONSTRSET} constraint-set]
    if {$synth_constraints eq "" || $impl_constraints ne $synth_constraints} {
        daedalus_fail "selected Vivado runs do not share one constraint set" 94
    }
    set impl_parent [daedalus_require_run_property $impl_run {PARENT SYNTH_RUN SYNTHESIS_RUN} parent-run]
    if {$impl_parent ne $synth_run} {
        daedalus_fail "selected implementation run is not linked to synthesis" 95
    }
}

proc daedalus_require_property_within {object property_name project_root label} {
    set properties [list_property $object]
    if {[lsearch -exact $properties $property_name] < 0} {
        return
    }
    if {[catch {get_property $property_name $object} value]} {
        daedalus_fail "cannot read $label $property_name: $value" 39
    }
    if {$value eq ""} {
        return
    }
    if {![daedalus_is_within $project_root $value]} {
        daedalus_fail "$label $property_name escaped the declared root: $value" 40
    }
}

proc daedalus_require_nonempty_property_within {object property_name project_root label} {
    set properties [list_property $object]
    if {[lsearch -exact $properties $property_name] < 0} {
        daedalus_fail "$label lacks required $property_name" 83
    }
    if {[catch {get_property $property_name $object} value]} {
        daedalus_fail "cannot read $label $property_name: $value" 84
    }
    if {$value eq "" || ![daedalus_is_within $project_root $value]} {
        daedalus_fail "$label $property_name is not inside the declared root" 85
    }
}

proc daedalus_check_write_roots {project_root generated_root cache_root ip_user_files_root run_root} {
    set project [current_project]
    foreach {property_name required_root} [list \
        DIRECTORY $project_root \
        DEFAULT_LAUNCH_DIR $run_root \
        IP_OUTPUT_REPO $cache_root \
        IP.USER_FILES_DIR $ip_user_files_root \
        IP_USER_FILES_DIR $ip_user_files_root \
        IP_DEFAULT_OUTPUT_PATH $generated_root \
        IP_STATIC_SOURCE_DIR $ip_user_files_root \
        SIM.IPSTATIC_SOURCE_DIR $ip_user_files_root \
    ] {
        daedalus_require_property_within \
            $project $property_name $required_root "project"
    }
    foreach run [get_runs -quiet] {
        if {[catch {get_property IS_SYNTHESIS $run} is_synthesis]} {
            daedalus_fail "cannot classify run $run for write-root control: $is_synthesis" 86
        }
        if {$is_synthesis} {
            daedalus_require_nonempty_property_within \
                $run DIRECTORY $run_root "synthesis run $run"
        } else {
            daedalus_require_property_within \
                $run DIRECTORY $run_root "run $run"
        }
    }
}

proc daedalus_assert_dedicated_roots {project_root generated_root cache_root ip_user_files_root run_root evidence_root} {
    foreach {label dedicated_root} [list \
        generated $generated_root \
        cache $cache_root \
        ip_user_files $ip_user_files_root \
        runs $run_root \
        evidence $evidence_root \
    ] {
        if {![daedalus_is_within $project_root $dedicated_root] || [daedalus_path_key $dedicated_root] eq [daedalus_path_key $project_root]} {
            daedalus_fail "$label root is not a proper descendant of the project root" 87
        }
    }
}

proc daedalus_clear_run_hooks {} {
    foreach run [get_runs -quiet] {
        foreach property_name [lsort [lsearch -all -inline -glob [list_property $run] *TCL*]] {
            set hook_value [get_property $property_name $run]
            if {$hook_value ne ""} {
                puts "DAEDALUS_CLEAR_HOOK run=$run property=$property_name"
                if {[catch {set_property $property_name {} $run} hook_error]} {
                    daedalus_fail "cannot clear $property_name on $run: $hook_error" 15
                }
            }
        }
    }
}

proc daedalus_assert_no_run_hooks {} {
    foreach run [get_runs -quiet] {
        foreach property_name [lsort [lsearch -all -inline -glob [list_property $run] *TCL*]] {
            if {[catch {get_property $property_name $run} hook_value]} {
                daedalus_fail "cannot verify $property_name on $run: $hook_value" 56
            }
            if {$hook_value ne ""} {
                daedalus_fail "run Tcl hook survived clearing: run=$run property=$property_name" 57
            }
        }
    }
}

proc daedalus_refuse_run_input_overrides {} {
    foreach run [get_runs -quiet] {
        foreach property_name [list_property $run] {
            set property_key [string tolower [string map {{ } {} _ {} - {} . {}} $property_name]]
            set named_input_override [expr {[string match "*moreoptions" $property_key] || [string match "*includedirs" $property_key] || [string match "*argsfile" $property_key] || [string match "*argsfilepath" $property_key]}]
            if {!$named_input_override && ![string match "*args*" $property_key] && ![string match "*launchoptions" $property_key]} {
                continue
            }
            if {[catch {get_property $property_name $run} property_value]} {
                daedalus_fail "cannot read run input override $property_name on $run: $property_value" 81
            }
            if {($named_input_override || [string match "*launchoptions" $property_key]) && [string trim $property_value] ne ""} {
                daedalus_fail "run input override is refused: run=$run property=$property_name" 82
            }
            if {[regexp -nocase {(^|[[:space:]])-include_dirs([[:space:]=]|$)|(^|[[:space:]])-file([[:space:]=]|$)} $property_value]} {
                daedalus_fail "path-bearing run option is refused: run=$run property=$property_name" 87
            }
        }
    }
}

proc daedalus_refuse_custom_ip_repositories {primary_source_set} {
    # IP_REPO_PATHS admits third-party/user IP catalogs. Such catalogs can
    # contain component.xml metadata and XGUI Tcl, so path containment alone
    # cannot make them trusted execution inputs. Gate 1 accepts only the
    # vendor installation's built-in catalog and fails closed on every custom
    # fileset repository path.
    set property_observed 0
    set primary_property_observed 0
    set objects [concat [list [current_project]] [get_filesets -quiet]]
    foreach object $objects {
        set properties [list_property $object]
        if {[lsearch -exact -nocase $properties IP_REPO_PATHS] < 0} {
            continue
        }
        set property_observed 1
        if {$object eq $primary_source_set} {
            set primary_property_observed 1
        }
        if {[catch {get_property IP_REPO_PATHS $object} repository_paths]} {
            daedalus_fail "cannot read IP_REPO_PATHS on $object: $repository_paths" 58
        }
        if {[string trim $repository_paths] ne ""} {
            daedalus_fail "custom IP_REPO_PATHS is refused on $object" 59
        }
    }
    if {!$property_observed || !$primary_property_observed} {
        daedalus_fail "cannot prove empty IP_REPO_PATHS on the primary source fileset" 60
    }
}

proc daedalus_refuse_include_directories {primary_source_set} {
    # Gate 1 refuses transitive Verilog include search roots. Python also scans
    # the bound RTL bytes for the `include token before process admission; this
    # runtime check catches XPR parser/schema drift and post-generation changes.
    set property_observed 0
    set primary_property_observed 0
    set objects [concat [list [current_project]] [get_filesets -quiet]]
    foreach object $objects {
        set properties [list_property $object]
        if {[lsearch -exact -nocase $properties INCLUDE_DIRS] < 0} {
            continue
        }
        set property_observed 1
        if {$object eq $primary_source_set} {
            set primary_property_observed 1
        }
        if {[catch {get_property INCLUDE_DIRS $object} include_directories]} {
            daedalus_fail "cannot read INCLUDE_DIRS on $object: $include_directories" 63
        }
        if {[string trim $include_directories] ne ""} {
            daedalus_fail "transitive INCLUDE_DIRS is refused on $object" 64
        }
    }
    if {!$property_observed || !$primary_property_observed} {
        daedalus_fail "cannot prove empty INCLUDE_DIRS on the primary source fileset" 65
    }
}

proc daedalus_refuse_ambient_board_repositories {} {
    if {[catch {get_param board.repoPaths} ambient_board_paths]} {
        daedalus_fail "cannot verify ambient board.repoPaths: $ambient_board_paths" 75
    }
    if {[string trim $ambient_board_paths] ne ""} {
        daedalus_fail "ambient board.repoPaths is refused" 76
    }
}

proc daedalus_refuse_custom_board_repositories {} {
    set objects [concat [list [current_project]] [get_filesets -quiet]]
    foreach object $objects {
        set properties [list_property $object]
        foreach property_name {BOARD_PART_REPO_PATHS BOARD_REPO_PATHS} {
            if {[lsearch -exact -nocase $properties $property_name] < 0} {
                continue
            }
            if {[catch {get_property $property_name $object} repository_paths]} {
                daedalus_fail "cannot read $property_name on $object: $repository_paths" 73
            }
            if {[string trim $repository_paths] ne ""} {
                daedalus_fail "custom board repository is refused on $object" 74
            }
        }
    }
    daedalus_refuse_ambient_board_repositories
}

proc daedalus_require_vendor_ip_definitions {} {
    foreach ip [get_ips -all -quiet] {
        if {[catch {get_property IPDEF $ip} ip_definition]} {
            daedalus_fail "cannot read IPDEF for $ip: $ip_definition" 70
        }
        if {![string match "xilinx.com:*" $ip_definition]} {
            daedalus_fail "non-vendor IP definition is refused: $ip_definition" 71
        }
    }
}

proc daedalus_validate_expanded_graph {project_root generated_root cache_root ip_user_files_root run_root primary_source_set_name expected_part expected_board_part expected_top} {
    set selected_source_sets [get_filesets -quiet $primary_source_set_name]
    if {[llength $selected_source_sets] != 1} {
        daedalus_fail "selected design source fileset changed during graph expansion" 44
    }
    set primary_source_set [lindex $selected_source_sets 0]
    set design_source_sets [get_filesets -quiet -filter {FILESET_TYPE == "DesignSrcs"}]
    if {[lsearch -exact $design_source_sets $primary_source_set] < 0} {
        daedalus_fail "selected source fileset is no longer a design source set" 45
    }
    set actual_part [get_property PART [current_project]]
    if {[catch {get_property BOARD_PART [current_project]} actual_board_part]} {
        daedalus_fail "cannot read BOARD_PART during graph expansion: $actual_board_part" 89
    }
    set actual_top [get_property TOP $primary_source_set]
    if {$actual_part ne $expected_part || $actual_board_part ne $expected_board_part || $actual_top ne $expected_top} {
        daedalus_fail "project identity changed during graph expansion: part=$actual_part board_part=$actual_board_part top=$actual_top" 46
    }
    daedalus_refuse_custom_ip_repositories $primary_source_set
    daedalus_refuse_include_directories $primary_source_set
    daedalus_refuse_custom_board_repositories
    daedalus_require_vendor_ip_definitions
    daedalus_check_write_roots $project_root $generated_root $cache_root $ip_user_files_root $run_root
    daedalus_check_active_files $project_root
    daedalus_refuse_run_input_overrides
    daedalus_clear_run_hooks
    daedalus_assert_no_run_hooks
    return [list $actual_part $actual_board_part $actual_top]
}

proc daedalus_disable_incremental_reuse {selected_synth_run selected_impl_run} {
    foreach run [get_runs -quiet] {
        if {[catch {get_property IS_SYNTHESIS $run} is_synthesis]} {
            daedalus_fail "cannot classify run $run for incremental-reuse control: $is_synthesis" 15
        }
        set selected_implementation [expr {$run eq $selected_impl_run}]
        if {!$is_synthesis && !$selected_implementation} {
            continue
        }
        set properties [list_property $run]
        foreach {property_name desired_value} {
            AUTO_INCREMENTAL_CHECKPOINT 0
            INCREMENTAL_CHECKPOINT {}
        } {
            if {[lsearch -exact $properties $property_name] < 0} {
                daedalus_fail "required incremental property $property_name is unavailable on $run" 65
            }
            if {[catch {set_property $property_name $desired_value $run} property_error]} {
                daedalus_fail "cannot disable $property_name on $run: $property_error" 16
            }
            if {[catch {get_property $property_name $run} actual_value]} {
                daedalus_fail "cannot verify $property_name on $run: $actual_value" 66
            }
            if {$desired_value eq ""} {
                if {$actual_value ne ""} {
                    daedalus_fail "$property_name remained enabled on $run" 67
                }
            } elseif {![string equal -nocase $actual_value $desired_value] && !($desired_value eq "0" && [string equal -nocase $actual_value "false"])} {
                daedalus_fail "$property_name remained enabled on $run: $actual_value" 68
            }
        }
        if {$is_synthesis} {
            foreach property_name {
                WRITE_INCREMENTAL_SYNTH_CHECKPOINT
                WRITE_INCREMENTAL_SYNTH_DCP
            } {
                if {[lsearch -exact $properties $property_name] < 0} {
                    continue
                }
                if {[catch {set_property $property_name 0 $run} property_error]} {
                    daedalus_fail "cannot disable $property_name on $run: $property_error" 16
                }
                if {[catch {get_property $property_name $run} actual_value]} {
                    daedalus_fail "cannot verify $property_name on $run: $actual_value" 66
                }
                if {![string equal -nocase $actual_value "0"] && ![string equal -nocase $actual_value "false"]} {
                    daedalus_fail "$property_name remained enabled on $run: $actual_value" 68
                }
            }
        }
    }
}

proc daedalus_prepare_ip_sources {project_root} {
    # Cached OOC synthesis is not an authoritative source input. Disable cache
    # use and force regeneration of every active XCI/BD output product from
    # the bound project configuration before any synthesis run is launched.
    if {[catch {config_ip_cache -disable_cache} cache_error]} {
        daedalus_fail "cannot disable Vivado IP synthesis cache: $cache_error" 50
    }
    if {[catch {get_property IP_CACHE_PERMISSIONS [current_project]} cache_mode]} {
        daedalus_fail "cannot verify Vivado IP cache mode: $cache_mode" 51
    }
    if {![string equal -nocase $cache_mode "disabled"]} {
        daedalus_fail "Vivado IP cache did not become disabled: $cache_mode" 52
    }

    set targets {}
    foreach source [get_files -quiet] {
        set source_path [get_property NAME $source]
        set source_extension [string tolower [file extension $source_path]]
        if {$source_extension ni {.xci .bd}} {
            continue
        }
        if {![daedalus_is_within $project_root $source_path]} {
            daedalus_fail "IP/BD source escaped the declared root: $source_path" 53
        }
        lappend targets $source
    }
    if {[llength $targets] == 0} {
        return 0
    }
    if {[catch {reset_target all $targets} reset_target_error]} {
        daedalus_fail "reset IP/BD output products failed: $reset_target_error" 54
    }
    if {[catch {generate_target -force all $targets} generate_target_error]} {
        daedalus_fail "regenerate IP/BD output products failed: $generate_target_error" 55
    }
    if {[catch {get_property IP_CACHE_PERMISSIONS [current_project]} cache_mode]} {
        daedalus_fail "cannot reverify Vivado IP cache mode: $cache_mode" 61
    }
    if {![string equal -nocase $cache_mode "disabled"]} {
        daedalus_fail "Vivado IP cache changed during generation: $cache_mode" 62
    }
    return [llength $targets]
}

proc daedalus_check_active_files {project_root} {
    set refused_automation_extensions {.tcl .bat .cmd .exe .ps1}
    foreach source [get_files -quiet] {
        set source_path [get_property NAME $source]
        if {$source_path eq ""} {
            daedalus_fail "active project file has an empty NAME" 17
        }
        if {![daedalus_is_within $project_root $source_path]} {
            daedalus_fail "active project file escaped the declared root: $source_path" 18
        }
        # Vivado can execute a project file as unmanaged Tcl based on its
        # FILE_TYPE property regardless of the filename suffix.  Read the
        # property for every active file and refuse that mode globally.
        if {[catch {get_property FILE_TYPE $source} file_type]} {
            daedalus_fail "cannot read FILE_TYPE for active file $source_path: $file_type" 47
        }
        if {[string equal -nocase $file_type "Tcl"]} {
            daedalus_fail "active project FILE_TYPE Tcl is refused: $source_path" 48
        }
        set source_extension [string tolower [file extension $source_path]]
        set file_type_key [string tolower [string map {{ } {} _ {} - {}} $file_type]]
        set verilog_file_types {verilog systemverilog verilogheader systemverilogheader}
        set vhdl_file_types {vhdl vhdl2008}
        set verilog_extensions {.v .sv .vh .svh}
        set vhdl_extensions {.vhd .vhdl}
        if {$source_extension eq ".dcp" || $file_type_key in {designcheckpoint dcp}} {
            daedalus_fail "active design checkpoint input is refused: $source_path" 88
        }
        if {[string equal -nocase $file_type "XDC"] && $source_extension ne ".xdc"} {
            daedalus_fail "FILE_TYPE XDC requires an .xdc path: $source_path" 72
        }
        if {[lsearch -exact $verilog_file_types $file_type_key] >= 0 && [lsearch -exact $verilog_extensions $source_extension] < 0} {
            daedalus_fail "Verilog FILE_TYPE requires a Verilog suffix: $source_path" 77
        }
        if {[lsearch -exact $vhdl_file_types $file_type_key] >= 0 && [lsearch -exact $vhdl_extensions $source_extension] < 0} {
            daedalus_fail "VHDL FILE_TYPE requires a VHDL suffix: $source_path" 78
        }
        if {[lsearch -exact $verilog_extensions $source_extension] >= 0 && $file_type_key ne "" && [lsearch -exact $verilog_file_types $file_type_key] < 0} {
            daedalus_fail "Verilog suffix has a refused FILE_TYPE: $source_path" 79
        }
        if {[lsearch -exact $vhdl_extensions $source_extension] >= 0 && $file_type_key ne "" && [lsearch -exact $vhdl_file_types $file_type_key] < 0} {
            daedalus_fail "VHDL suffix has a refused FILE_TYPE: $source_path" 80
        }
        if {$source_extension in {.xcix .xco}} {
            daedalus_fail "opaque IP/core-container input is refused: $source_path" 69
        }
        if {$source_extension eq ".xdc"} {
            # An .xdc path can be retyped by Vivado as FILE_TYPE Tcl, which is
            # unrestricted unmanaged Tcl rather than an XDC constraint file.
            # Suffix alone is therefore not an admission decision.
            if {![string equal -nocase $file_type "XDC"]} {
                daedalus_fail "XDC path has refused FILE_TYPE $file_type: $source_path" 49
            }
            continue
        }
        if {[lsearch -exact $refused_automation_extensions $source_extension] >= 0} {
            daedalus_fail "active project automation is refused: $source_path" 19
        }
    }
}

proc daedalus_write_common_summary {summary_file phase project_file part board_part top synth_run impl_run} {
    puts $summary_file "schema=daedalus-vivado-flow-summary/1"
    puts $summary_file "phase=$phase"
    puts $summary_file "tool=[version -short]"
    puts $summary_file "project=[daedalus_normalize $project_file]"
    puts $summary_file "part=$part"
    puts $summary_file "board_part=$board_part"
    puts $summary_file "top=$top"
    puts $summary_file "synth_run=$synth_run"
    puts $summary_file "impl_run=$impl_run"
}

if {[llength $argv] != 10} {
    daedalus_fail "expected 10 Tcl arguments, received [llength $argv]" 2
}

set phase [lindex $argv 0]
set project_root [daedalus_normalize [lindex $argv 1]]
set project_file [daedalus_normalize [lindex $argv 2]]
set output_dir [daedalus_normalize [lindex $argv 3]]
set expected_part [lindex $argv 4]
set expected_board_part [lindex $argv 5]
set expected_top [lindex $argv 6]
set synth_run_name [lindex $argv 7]
set impl_run_name [lindex $argv 8]
set jobs [lindex $argv 9]

if {$phase ni {inspect synth impl}} {
    daedalus_fail "unsupported phase: $phase" 3
}
if {![string is integer -strict $jobs] || $jobs < 1 || $jobs > 64} {
    daedalus_fail "jobs must be an integer between 1 and 64" 4
}
if {![file isdirectory $project_root]} {
    daedalus_fail "project root is not a directory" 5
}
if {![file isfile $project_file] || [string tolower [file extension $project_file]] ne ".xpr"} {
    daedalus_fail "project file is not a regular XPR" 6
}
if {![daedalus_is_within $project_root $project_file]} {
    daedalus_fail "project file escaped the declared root" 7
}
set evidence_root [file join $project_root .daedalus-chip]
set project_stem [file rootname [file tail $project_file]]
set generated_root [file join $project_root "${project_stem}.gen"]
set cache_root [file join $project_root "${project_stem}.cache"]
set ip_user_files_root [file join $project_root "${project_stem}.ip_user_files"]
set run_root [file join $project_root "${project_stem}.runs"]
daedalus_assert_dedicated_roots \
    $project_root $generated_root $cache_root $ip_user_files_root $run_root $evidence_root
if {![daedalus_is_within $evidence_root $output_dir] || [daedalus_path_key $output_dir] eq [daedalus_path_key $evidence_root]} {
    daedalus_fail "output directory must be a proper descendant of the dedicated evidence root" 8
}

daedalus_refuse_ambient_board_repositories
if {[catch {open_project $project_file} open_error]} {
    daedalus_fail "open_project failed: $open_error" 10
}

set actual_part [get_property PART [current_project]]
if {[catch {get_property BOARD_PART [current_project]} actual_board_part]} {
    daedalus_fail "cannot read project BOARD_PART: $actual_board_part" 89
}
set source_sets [get_filesets -quiet -filter {FILESET_TYPE == "DesignSrcs"}]
if {[llength $source_sets] == 0} {
    daedalus_fail "project has no design source fileset" 11
}
set primary_source_set [lindex $source_sets 0]
if {[llength [get_filesets -quiet sources_1]] == 1} {
    set primary_source_set [get_filesets sources_1]
}
set actual_top [get_property TOP $primary_source_set]
if {$actual_part ne $expected_part || $actual_board_part ne $expected_board_part || $actual_top ne $expected_top} {
    daedalus_fail "project identity mismatch: part=$actual_part board_part=$actual_board_part top=$actual_top" 12
}

set primary_source_set_name $primary_source_set
lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
update_compile_order -fileset $primary_source_set
lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
set regenerated_ip_source_count 0
if {$phase ne "inspect"} {
    set regenerated_ip_source_count [daedalus_prepare_ip_sources $project_root]
    # Target generation can materialize/register new files and synthesis runs.
    # Re-establish every execution and write invariant over that expanded
    # object graph before any synthesis command is allowed to start.
    lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
    update_compile_order -fileset $primary_source_set
    lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
}
file mkdir $output_dir
set summary_path [file join $output_dir "${phase}_summary.txt"]
if {[catch {open $summary_path w} summary_file]} {
    daedalus_fail "cannot create summary: $summary_file" 13
}
daedalus_write_common_summary $summary_file $phase $project_file $actual_part $actual_board_part $actual_top $synth_run_name $impl_run_name
if {$phase ne "inspect"} {
    puts $summary_file "ip_cache=disabled"
    puts $summary_file "regenerated_ip_source_count=$regenerated_ip_source_count"
}

set synth_run [daedalus_require_run $synth_run_name synth_run]
set impl_run [daedalus_require_run $impl_run_name impl_run]
daedalus_validate_selected_runs $synth_run $impl_run $primary_source_set_name $expected_part
daedalus_require_nonempty_property_within $synth_run DIRECTORY $run_root "selected synthesis run"
daedalus_require_nonempty_property_within $impl_run DIRECTORY $run_root "selected implementation run"

if {$phase eq "inspect"} {
    puts $summary_file "synth_status=[get_property STATUS $synth_run]"
    puts $summary_file "synth_progress=[get_property PROGRESS $synth_run]"
    puts $summary_file "impl_status=[get_property STATUS $impl_run]"
    puts $summary_file "impl_progress=[get_property PROGRESS $impl_run]"
    set ip_count 0
    set locked_ip_count 0
    foreach ip [get_ips -quiet] {
        incr ip_count
        if {![catch {get_property IS_LOCKED $ip} locked] && $locked} {
            incr locked_ip_count
        }
    }
    puts $summary_file "ip_count=$ip_count"
    puts $summary_file "locked_ip_count=$locked_ip_count"
    close $summary_file
    puts "DAEDALUS_VIVADO_RESULT phase=inspect status=complete"
    close_project
    exit 0
}

daedalus_disable_incremental_reuse $synth_run $impl_run

if {$phase eq "synth"} {
    if {[catch {reset_run $impl_run} reset_impl_error]} {
        daedalus_fail "reset implementation run failed: $reset_impl_error" 20
    }
    set synthesis_runs {}
    foreach run [get_runs -quiet] {
        if {![catch {get_property IS_SYNTHESIS $run} is_synthesis] && $is_synthesis} {
            lappend synthesis_runs $run
        }
    }
    if {[llength $synthesis_runs] == 0} {
        daedalus_fail "project has no synthesis runs" 21
    }
    if {[catch {reset_run $synthesis_runs} reset_error]} {
        daedalus_fail "reset synthesis runs failed: $reset_error" 22
    }
    daedalus_disable_incremental_reuse $synth_run $impl_run
    daedalus_validate_selected_runs $synth_run $impl_run $primary_source_set_name $expected_part
    if {[catch {launch_runs $synth_run -jobs $jobs} launch_error]} {
        daedalus_fail "launch synthesis failed: $launch_error" 23
    }
    if {[catch {wait_on_run $synth_run} wait_error]} {
        daedalus_fail "wait_on_run synthesis failed: $wait_error" 24
    }
    set run_status [get_property STATUS $synth_run]
    set run_progress [get_property PROGRESS $synth_run]
    puts $summary_file "status=$run_status"
    puts $summary_file "progress=$run_progress"
    puts $summary_file "jobs=$jobs"
    if {![string match "*Complete*" $run_status] || $run_progress ne "100%"} {
        close $summary_file
        daedalus_fail "synthesis did not complete: status=$run_status progress=$run_progress" 25
    }
    if {[catch {open_run $synth_run} open_run_error]} {
        close $summary_file
        daedalus_fail "open synthesis run failed: $open_run_error" 26
    }
    foreach {report_command report_name} {
        report_utilization utilization.rpt
        report_drc drc.rpt
        report_methodology methodology.rpt
    } {
        if {[catch {$report_command -file [file join $output_dir $report_name]} report_error]} {
            close $summary_file
            daedalus_fail "$report_command failed: $report_error" 27
        }
    }
    if {[catch {report_timing_summary -report_unconstrained -check_timing_verbose -max_paths 10 -file [file join $output_dir timing_summary.rpt]} timing_error]} {
        close $summary_file
        daedalus_fail "report_timing_summary failed: $timing_error" 28
    }
    if {[catch {write_checkpoint -force [file join $output_dir design.dcp]} checkpoint_error]} {
        close $summary_file
        daedalus_fail "write synthesis checkpoint failed: $checkpoint_error" 29
    }
    close $summary_file
    puts "DAEDALUS_VIVADO_RESULT phase=synth status=complete progress=$run_progress"
    close_design
    close_project
    exit 0
}

# Implementation never trusts a pre-existing Complete/100% run.  It resets all
# synthesis state and regenerates a synthesis checkpoint from the currently
# opened, identity-checked project before implementation begins.
if {[catch {reset_run $impl_run} reset_error]} {
    close $summary_file
    daedalus_fail "reset implementation run failed: $reset_error" 31
}
set synthesis_runs {}
foreach run [get_runs -quiet] {
    if {![catch {get_property IS_SYNTHESIS $run} is_synthesis] && $is_synthesis} {
        lappend synthesis_runs $run
    }
}
if {[llength $synthesis_runs] == 0} {
    close $summary_file
    daedalus_fail "project has no synthesis runs" 30
}
if {[catch {reset_run $synthesis_runs} reset_synth_error]} {
    close $summary_file
    daedalus_fail "reset synthesis runs failed: $reset_synth_error" 41
}
daedalus_disable_incremental_reuse $synth_run $impl_run
daedalus_validate_selected_runs $synth_run $impl_run $primary_source_set_name $expected_part
if {[catch {launch_runs $synth_run -jobs $jobs} launch_synth_error]} {
    close $summary_file
    daedalus_fail "launch fresh synthesis failed: $launch_synth_error" 42
}
if {[catch {wait_on_run $synth_run} wait_synth_error]} {
    close $summary_file
    daedalus_fail "wait_on_run fresh synthesis failed: $wait_synth_error" 43
}
set synth_status [get_property STATUS $synth_run]
set synth_progress [get_property PROGRESS $synth_run]
puts $summary_file "fresh_synthesis=1"
puts $summary_file "synth_status=$synth_status"
puts $summary_file "synth_progress=$synth_progress"
if {![string match "*Complete*" $synth_status] || $synth_progress ne "100%"} {
    close $summary_file
    daedalus_fail "fresh synthesis did not complete: status=$synth_status progress=$synth_progress" 44
}
if {[catch {open_run $synth_run} open_synth_error]} {
    close $summary_file
    daedalus_fail "open fresh synthesis run failed: $open_synth_error" 45
}
if {[catch {write_checkpoint -force [file join $output_dir synth_design.dcp]} synth_checkpoint_error]} {
    close $summary_file
    daedalus_fail "write fresh synthesis checkpoint failed: $synth_checkpoint_error" 46
}
close_design
lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
update_compile_order -fileset $primary_source_set
lassign [daedalus_validate_expanded_graph $project_root $generated_root $cache_root $ip_user_files_root $run_root $primary_source_set_name $expected_part $expected_board_part $expected_top] actual_part actual_board_part actual_top
daedalus_disable_incremental_reuse $synth_run $impl_run
daedalus_validate_selected_runs $synth_run $impl_run $primary_source_set_name $expected_part
if {[catch {launch_runs $impl_run -to_step write_bitstream -jobs $jobs} launch_error]} {
    close $summary_file
    daedalus_fail "launch implementation failed: $launch_error" 32
}
if {[catch {wait_on_run $impl_run} wait_error]} {
    close $summary_file
    daedalus_fail "wait_on_run implementation failed: $wait_error" 33
}
set run_status [get_property STATUS $impl_run]
set run_progress [get_property PROGRESS $impl_run]
puts $summary_file "status=$run_status"
puts $summary_file "progress=$run_progress"
puts $summary_file "jobs=$jobs"
if {![string match "*Complete*" $run_status] || $run_progress ne "100%"} {
    close $summary_file
    daedalus_fail "implementation did not complete: status=$run_status progress=$run_progress" 34
}
if {[catch {open_run $impl_run} open_run_error]} {
    close $summary_file
    daedalus_fail "open implementation run failed: $open_run_error" 35
}
foreach {report_command report_name} {
    report_utilization utilization.rpt
    report_drc drc.rpt
    report_methodology methodology.rpt
    report_route_status route_status.rpt
} {
    if {[catch {$report_command -file [file join $output_dir $report_name]} report_error]} {
        close $summary_file
        daedalus_fail "$report_command failed: $report_error" 36
    }
}
if {[catch {report_timing_summary -report_unconstrained -check_timing_verbose -max_paths 10 -file [file join $output_dir timing_summary.rpt]} timing_error]} {
    close $summary_file
    daedalus_fail "report_timing_summary failed: $timing_error" 36
}
if {[catch {write_checkpoint -force [file join $output_dir design.dcp]} checkpoint_error]} {
    close $summary_file
    daedalus_fail "write implementation checkpoint failed: $checkpoint_error" 37
}
if {[catch {write_bitstream -force [file join $output_dir design.bit]} bitstream_error]} {
    close $summary_file
    daedalus_fail "write bitstream failed: $bitstream_error" 38
}
close $summary_file
puts "DAEDALUS_VIVADO_RESULT phase=impl status=complete progress=$run_progress"
close_design
close_project
exit 0
