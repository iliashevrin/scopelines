#!/bin/sh
# Runs the command (by default, a shell) as the owner of the mounted results/
# directory, so that the outputs written there belong to the host user, and
# writing them never fails; a container started with --user runs as is.
if [ "$(id -u)" = 0 ] && [ -d /scopelines/results ]; then
	uid=$(stat -c %u /scopelines/results)
	gid=$(stat -c %g /scopelines/results)
	if [ "$uid" != 0 ]; then
		exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
	fi
fi
exec "$@"
