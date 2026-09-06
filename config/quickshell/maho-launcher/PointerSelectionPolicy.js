.pragma library

function topIndex(count) {
    return Number(count || 0) > 0 ? 0 : -1
}

function movedEnough(anchorX, anchorY, pointerX, pointerY, threshold) {
    const dx = Number(pointerX) - Number(anchorX)
    const dy = Number(pointerY) - Number(anchorY)
    const minimum = Math.max(0, Number(threshold || 0))
    return dx * dx + dy * dy >= minimum * minimum
}

function hoverIndex(currentIndex, rowIndex, pointerHasAuthority) {
    return pointerHasAuthority ? Number(rowIndex) : Number(currentIndex)
}

function clickIndex(rowIndex) {
    return Number(rowIndex)
}
