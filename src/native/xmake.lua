add_rules("mode.debug", "mode.release")
add_rules("plugin.compile_commands.autoupdate")


target("native")
    is_plat("windows")
    set_kind("shared")
    set_languages("c++20")
    add_files("src/*.cpp")
    add_links("dxgi")
