/**
 * Every value this app keeps in storage is under `dirigent.`. A module that builds a kept store
 * imports this before it builds one, because a store reads its key as it is built.
 */

import { setStoredPrefix } from '@winterop-com/sokkel-ui/lib/stored'

setStoredPrefix('dirigent.')
