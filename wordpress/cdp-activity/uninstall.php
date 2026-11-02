<?php
/**
 * Runs when the plugin is deleted from Plugins > Installed Plugins.
 * Removes the CDP Drafter role, the added capabilities, and the plugin option.
 * Toolkit Activity posts, their fields, and filter terms are kept: they are IF content.
 * To delete those too, delete the activities in Toolkit Activities first.
 */
if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}
remove_role( 'cdp_drafter' );
$cdp_caps = array( 'edit_activities', 'edit_others_activities', 'publish_activities', 'read_private_activities',
	'delete_activities', 'delete_private_activities', 'delete_published_activities', 'delete_others_activities',
	'edit_private_activities', 'edit_published_activities' );
foreach ( array( 'administrator', 'editor' ) as $cdp_role_name ) {
	$cdp_role = get_role( $cdp_role_name );
	if ( $cdp_role ) {
		foreach ( $cdp_caps as $cdp_cap ) {
			$cdp_role->remove_cap( $cdp_cap );
		}
	}
}
delete_option( 'cdp_roles_version' );
