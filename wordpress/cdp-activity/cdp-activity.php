<?php
/**
 * Plugin Name: CDP Toolkit Activities
 * Description: Toolkit Activity post type, filters, an "Activity details" box, and a draft-only "CDP Drafter" role for the Collaborative Discussion Toolkit migration.
 * Version: 0.3.1
 * Requires at least: 6.4
 * Requires PHP: 7.4
 *
 * Settings (optional, in wp-config.php, before activation):
 *   define( 'CDP_ACTIVITY_SLUG', 'toolkit/activity' );   // public URL base for activity pages
 *   define( 'CDP_EMBED_HOSTS', 'docs.google.com,www.youtube.com,www.youtube-nocookie.com,player.vimeo.com' ); // iframes allowed in activities
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const CDP_POST_TYPE = 'cdp_activity';
const CDP_ROLES_VERSION = '2';

function cdp_meta_fields() {
	return array(
		'cdp_activity_id'      => array( 'string', 'sanitize_title', 'Toolkit ID (old address)' ),
		'cdp_number'           => array( 'string', 'sanitize_text_field', 'Number (for example 2.6)' ),
		'cdp_duration_minutes' => array( 'integer', 'absint', 'Time (minutes)' ),
		'cdp_contributor'      => array( 'string', 'sanitize_text_field', 'Submitted by' ),
		'cdp_pdf_url'          => array( 'string', 'esc_url_raw', 'PDF link' ),
		'cdp_source_url'       => array( 'string', 'esc_url_raw', 'Old Toolkit page' ),
		'cdp_image_credit'     => array( 'string', 'sanitize_text_field', 'Image credit' ),
	);
}

function cdp_default_terms() {
	return array(
		'cdp_module' => array(
			'Module 1: Introduction to Collaborative Discussion',
			'Module 2: Creative Collaboration',
			'Module 3: Critical Collaboration',
			'Module 4: Culturally Responsive Collaboration',
			'Module 5: Civic Collaboration',
		),
		'cdp_level'  => array( 'Beginner', 'Advanced' ),
		'cdp_format' => array( 'Asynchronous', 'Connection', 'Emotion', 'Facilitation', 'Listening', 'Playful',
			'Professional', 'Tactile', 'Warm-up' ),
	);
}

function cdp_register() {
	$slug = defined( 'CDP_ACTIVITY_SLUG' ) ? CDP_ACTIVITY_SLUG : 'toolkit/activity';
	register_post_type( CDP_POST_TYPE, array(
		'label'           => 'Toolkit Activities',
		'labels'          => array( 'singular_name' => 'Toolkit Activity', 'add_new_item' => 'Add New Activity',
			'edit_item' => 'Edit Activity', 'search_items' => 'Search Activities' ),
		'public'          => true,
		'show_in_rest'    => true,
		'rest_base'       => 'cdp-activities',
		'menu_icon'       => 'dashicons-groups',
		'has_archive'     => false, // the Toolkit listing page (for example a FacetWP page) is built by IF
		'rewrite'         => array( 'slug' => $slug, 'with_front' => false ),
		'supports'        => array( 'title', 'editor', 'thumbnail', 'custom-fields', 'revisions' ),
		'capability_type' => array( 'activity', 'activities' ),
		'map_meta_cap'    => true,
	) );

	$labels = array( 'cdp_module' => 'Modules', 'cdp_level' => 'Levels', 'cdp_format' => 'Tags (formats)' );
	foreach ( $labels as $tax => $label ) {
		register_taxonomy( $tax, CDP_POST_TYPE, array(
			'label'              => $label,
			'public'             => false,
			'publicly_queryable' => false,
			'show_ui'            => true,
			'show_admin_column'  => true,
			'show_in_rest'       => true,
			'rest_base'          => $tax,
			'hierarchical'       => true, // checkbox list in the editor; terms are set by administrators
			'capabilities'       => array(
				'manage_terms' => 'manage_categories',
				'edit_terms'   => 'manage_categories',
				'delete_terms' => 'manage_categories',
				'assign_terms' => 'edit_activities',
			),
		) );
	}

	foreach ( cdp_meta_fields() as $key => $f ) {
		register_post_meta( CDP_POST_TYPE, $key, array(
			'type'              => $f[0],
			'single'            => true,
			'show_in_rest'      => true,
			'sanitize_callback' => $f[1],
			'revisions_enabled' => true, // Activity details are kept in Revisions with the text
			'auth_callback'     => function () {
				return current_user_can( 'edit_activities' );
			},
		) );
	}
}
add_action( 'init', 'cdp_register' );

// Meta is readable over REST only by people who can edit activities.
add_filter( 'rest_prepare_' . CDP_POST_TYPE, function ( $response ) {
	if ( ! current_user_can( 'edit_activities' ) ) {
		$data = $response->get_data();
		unset( $data['meta'] );
		$response->set_data( $data );
	}
	return $response;
} );

// GET /wp-json/wp/v2/cdp-activities?cdp_activity_id=<id> finds one activity (editors only).
add_filter( 'rest_' . CDP_POST_TYPE . '_query', function ( $args, $request ) {
	$id = $request->get_param( 'cdp_activity_id' );
	if ( $id && current_user_can( 'edit_activities' ) ) {
		$args['meta_query'] = array( array( 'key' => 'cdp_activity_id', 'value' => sanitize_title( $id ) ) );
	}
	return $args;
}, 10, 2 );

// Embedded slides and video: allow iframes from approved hosts only, for people who edit activities.
function cdp_embed_hosts() {
	$hosts = defined( 'CDP_EMBED_HOSTS' ) ? CDP_EMBED_HOSTS : 'docs.google.com,www.youtube.com,www.youtube-nocookie.com,player.vimeo.com';
	return array_filter( array_map( 'trim', explode( ',', $hosts ) ) );
}
add_filter( 'wp_kses_allowed_html', function ( $tags, $context ) {
	if ( 'post' === $context && current_user_can( 'edit_activities' ) ) {
		$tags['iframe'] = array( 'src' => true, 'width' => true, 'height' => true, 'title' => true,
			'allow' => true, 'allowfullscreen' => true, 'frameborder' => true, 'loading' => true );
	}
	return $tags;
}, 10, 2 );
add_filter( 'wp_insert_post_data', function ( $data ) {
	if ( CDP_POST_TYPE !== $data['post_type'] || current_user_can( 'unfiltered_html' ) ) {
		return $data;
	}
	$hosts   = cdp_embed_hosts();
	$kept    = array();
	$content = wp_unslash( $data['post_content'] );
	// Each iframe element, including anything between its tags or a missing closing tag.
	$content = preg_replace_callback( '#<iframe\b[^>]*>.*?(?:</iframe\s*>|$)#is', function ( $m ) use ( $hosts, &$kept ) {
		if ( ! preg_match( '#^<iframe\b[^>]*>#i', $m[0], $open ) ) {
			return '';
		}
		$tag = new WP_HTML_Tag_Processor( $open[0] . '</iframe>' ); // the processor needs the closing tag
		if ( ! $tag->next_tag( 'iframe' ) ) {
			return '';
		}
		$src  = (string) $tag->get_attribute( 'src' ); // the real src attribute only, never data-src
		$host = strtolower( (string) wp_parse_url( $src, PHP_URL_HOST ) );
		if ( '' === $host || ! in_array( $host, $hosts, true ) ) {
			return '';
		}
		$kept[] = $open[0] . '</iframe>';
		return "\x00cdp-embed-" . ( count( $kept ) - 1 ) . "\x00";
	}, $content );
	$content = preg_replace( '#<iframe\b[^>]*>#i', '', $content ); // any stray opening tag left over
	foreach ( $kept as $i => $iframe ) {
		$content = str_replace( "\x00cdp-embed-{$i}\x00", $iframe, $content );
	}
	$data['post_content'] = wp_slash( $content );
	return $data;
}, 20 );

// Light styling for the Toolkit's text boxes (callouts), on activity pages only. The theme or
// Breakdance template can override it.
add_action( 'wp_head', function () {
	if ( is_singular( CDP_POST_TYPE ) || is_preview() ) {
		echo '<style id="cdp-activity-css">.cdp-callout{background:#f4f2fe;border-left:4px solid #6248dc;'
			. 'border-radius:6px;padding:.75em 1em;margin:1.25em 0}.cdp-callout p{margin:.25em 0}</style>';
	}
} );

// "Activity details" box in the editor, so staff never need the raw custom fields panel.
add_action( 'add_meta_boxes_' . CDP_POST_TYPE, function () {
	add_meta_box( 'cdp_details', 'Activity details', 'cdp_details_box', CDP_POST_TYPE, 'side', 'high' );
} );
function cdp_details_box( $post ) {
	wp_nonce_field( 'cdp_details', 'cdp_details_nonce' );
	foreach ( cdp_meta_fields() as $key => $f ) {
		if ( in_array( $key, array( 'cdp_activity_id', 'cdp_source_url' ), true ) ) {
			continue; // set by the migration only
		}
		$value = get_post_meta( $post->ID, $key, true );
		printf( '<p><label for="%1$s"><strong>%2$s</strong></label><br><input type="%3$s" id="%1$s" name="%1$s" value="%4$s" style="width:100%%"></p>',
			esc_attr( $key ), esc_html( $f[2] ), 'integer' === $f[0] ? 'number' : 'text', esc_attr( $value ) );
	}
}
add_action( 'save_post_' . CDP_POST_TYPE, function ( $post_id ) {
	if ( ! isset( $_POST['cdp_details_nonce'] ) || ! wp_verify_nonce( sanitize_key( $_POST['cdp_details_nonce'] ), 'cdp_details' ) ) {
		return;
	}
	if ( ( defined( 'DOING_AUTOSAVE' ) && DOING_AUTOSAVE ) || ! current_user_can( 'edit_post', $post_id ) ) {
		return;
	}
	foreach ( cdp_meta_fields() as $key => $f ) {
		if ( isset( $_POST[ $key ] ) && ! in_array( $key, array( 'cdp_activity_id', 'cdp_source_url' ), true ) ) {
			update_post_meta( $post_id, $key, call_user_func( $f[1], wp_unslash( $_POST[ $key ] ) ) );
		}
	}
} );

// Roles and default terms. Runs on activation, and once on init if missing (for must-use installs).
function cdp_setup_roles_and_terms() {
	$all = array( 'edit_activities', 'edit_others_activities', 'publish_activities', 'read_private_activities',
		'delete_activities', 'delete_private_activities', 'delete_published_activities', 'delete_others_activities',
		'edit_private_activities', 'edit_published_activities' );
	foreach ( array( 'administrator', 'editor' ) as $name ) {
		$role = get_role( $name );
		if ( $role ) {
			foreach ( $all as $cap ) {
				$role->add_cap( $cap );
			}
		}
	}
	remove_role( 'cdp_drafter' );
	// Creates and edits its own unpublished activities and uploads their files. Cannot publish,
	// cannot edit other people's activities, cannot create or change filter terms.
	add_role( 'cdp_drafter', 'CDP Drafter', array( 'read' => true, 'upload_files' => true,
		'edit_activities' => true, 'delete_activities' => true ) );
	cdp_register();
	foreach ( cdp_default_terms() as $tax => $terms ) {
		foreach ( $terms as $term ) {
			if ( ! term_exists( $term, $tax ) ) {
				wp_insert_term( $term, $tax );
			}
		}
	}
	update_option( 'cdp_roles_version', CDP_ROLES_VERSION );
}
register_activation_hook( __FILE__, function () {
	cdp_setup_roles_and_terms();
	flush_rewrite_rules();
} );
add_action( 'init', function () {
	if ( get_option( 'cdp_roles_version' ) !== CDP_ROLES_VERSION ) {
		cdp_setup_roles_and_terms();
	}
}, 20 );
register_deactivation_hook( __FILE__, 'flush_rewrite_rules' );
