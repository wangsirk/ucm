file(GLOB_RECURSE UCM_LUSTRE_STORE_CC_SOURCE_FILES "./cc/*.cc")
add_library(lustrestore SHARED ${UCM_LUSTRE_STORE_CC_SOURCE_FILES})
target_include_directories(lustrestore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/cc)
target_compile_definitions(lustrestore PRIVATE HAVE_LUSTRE_API)
target_link_libraries(lustrestore PUBLIC storeintf infra_logger lustreapi)

file(RELATIVE_PATH INSTALL_REL_PATH ${CMAKE_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR})
install(TARGETS lustrestore LIBRARY DESTINATION ${INSTALL_REL_PATH} COMPONENT ucm)
