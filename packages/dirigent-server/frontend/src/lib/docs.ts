/**
 * The escape hatch out of a screen and into the API that answers it.
 *
 * EVERY LISTING IS A READ SOMEBODY CAN MAKE THEMSELVES, and the screen is one rendering of it
 * rather than the only way to it. The chip in a listing's corner opens this instance's own
 * OpenAPI document at the resource the screen is drawing.
 *
 * THE ANCHOR IS SWAGGER UI'S OWN. It writes `#/<tag>` on the heading of every tag section and
 * links its own contents that way, and the tag is what `APIRouter(tags=[...])` declared. So
 * `/docs#/runs` is the runs section, opened by the same fragment the page uses on itself.
 *
 * `/docs` IS AT THE ROOT, whatever prefix the versioned API mounted at, so this is a plain
 * path and not something `lib/api` composes.
 */

/** The router tags this bundle draws a screen for. `APIRouter(tags=[...])` on the server. */
export type DocsTag =
    | 'pipelines'
    | 'runs'
    | 'triggers'
    | 'connections'
    | 'blocks'
    | 'schemas'
    | 'users'
    | 'workers'
    | 'alerts'
    | 'system'

/** Where the interactive documentation for one resource is. */
export function docsHref(tag: DocsTag): string {
    return `/docs#/${tag}`
}

/** What the chip says. Short, because it sits on a heading beside the screen's own actions. */
export const API_LABEL = 'API'

/** This instance's own OpenAPI document, rendered. It is at the root, whatever the API mounted at. */
export const API_DOCS_URL = '/docs'

/** Where everything this app does is written down. Outside the instance, so an absolute URL. */
export const DOCS_URL = 'https://github.com/winterop-com/dirigent/tree/main/docs'
