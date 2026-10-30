;(function () {
    // Duplicated from lib/theme.ts: this runs before any module is fetched, so it cannot import
    // them. The test beside that module asserts the two lists agree.
    var known = ['dirigent', 'paper', 'contrast']
    var chosen = 'dirigent'
    try {
        var stored = localStorage.getItem('dirigent.palette')
        if (known.indexOf(stored) !== -1) chosen = stored
    } catch (denied) {
        // Storage denied. The default is already in `chosen`, and the app runs in it for as
        // long as this document is open.
    }
    document.documentElement.setAttribute('data-theme', chosen)
})()
