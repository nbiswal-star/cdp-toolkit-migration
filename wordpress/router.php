<?php
// Router for PHP's built-in server: serve real files and directories, and send
// everything else to WordPress. Directories must go back to the built-in server
// so routes such as /wp-admin/ use their own index.php.
$path = parse_url( $_SERVER['REQUEST_URI'], PHP_URL_PATH );
if ( '/' !== $path && file_exists( __DIR__ . $path ) ) {
	return false;
}
$_SERVER['SCRIPT_NAME'] = '/index.php';
require __DIR__ . '/index.php';
