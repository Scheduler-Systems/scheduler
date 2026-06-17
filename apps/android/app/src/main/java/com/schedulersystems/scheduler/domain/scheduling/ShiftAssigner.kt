package com.schedulersystems.scheduler.domain.scheduling

data class AssignShiftsInput(
    val currentPriorities: List<String>,
    val stationNum: Int,
    val numOfPeople: Int,
    val stations: List<PartialStationConfig?> = emptyList()
)

data class PartialStationConfig(
    val morning: Boolean? = null,
    val afternoon: Boolean? = null,
    val night: Boolean? = null
)

data class AssignShiftsOutput(
    val assignments: List<List<String>>,
    val grids: List<List<List<String?>>>
)

fun assignShifts(input: AssignShiftsInput): AssignShiftsOutput {
    val stations = (0 until input.stationNum).map { s ->
        val override = input.stations.getOrNull(s)
        StationConfig(
            morning = override?.morning ?: true,
            afternoon = override?.afternoon ?: true,
            night = override?.night ?: true,
            numOfPeople = input.numOfPeople,
            stationNum = s + 1
        )
    }

    val mat = Array(7) { arrayOf("", "", "") }
    for (i in 0 until 21) {
        mat[i / 3][i % 3] = input.currentPriorities.getOrElse(i) { "" }
    }

    val arrayListMat2 = stations.map { station ->
        Array(7) { day ->
            arrayOfNulls<String>(3).also {
                if (station.morning) it[0] = ""
                if (station.afternoon) it[1] = ""
                if (station.night) it[2] = ""
            }
        }.map { it.toMutableList() }.toMutableList()
    }.toMutableList()

    val resultGrids = organizeMatrices(mat = mat.map { it.toList() }, arrayListMat2 = arrayListMat2, stations = stations)

    val assignments = resultGrids.map { grid ->
        List(21) { i ->
            grid[i / 3][i % 3] ?: ""
        }
    }

    return AssignShiftsOutput(assignments = assignments, grids = resultGrids)
}

// ========== Helpers ==========

private fun commaCount(s: String?): Int = s?.count { it == ',' } ?: 0

private fun names(list1: MutableList<String>, list3: MutableList<Int>, list5: MutableList<Int>, str: String) {
    var istart = 0
    for (iend in str.indices) {
        if (str[iend] == ',') {
            val name = str.substring(istart, iend) + ", "
            if (name !in list1) {
                list1.add(name)
                list3.add(0)
                list5.add(0)
            }
            istart = iend + 2
        }
    }
}

private fun extractNames(str: String): List<String> {
    val result = mutableListOf<String>()
    var list3 = mutableListOf<Int>()
    var list5 = mutableListOf<Int>()
    names(result, list3, list5, str)
    return result
}

private fun split(list1: List<String>, list2: List<String?>, list3: MutableList<Int>) {
    for (str in list2) {
        if (str == null) continue
        var istart = 0
        for (iend in str.indices) {
            if (str[iend] == ',') {
                val sub = str.substring(istart, iend) + ", "
                if (sub in str) {
                    val idx = list1.indexOf(sub)
                    if (idx >= 0) list3[idx]++
                }
                istart = iend + 2
            }
        }
    }
}

private fun isWithoutWords(list2: List<String?>): Boolean {
    return list2.all { it.isNullOrEmpty() }
}

private fun containsSubString(list: List<String?>, sub: String): Boolean {
    return list.any { it?.contains(sub) == true }
}

private fun cellKey(i: Int, j: Int): String = "$i$j"

private fun list12Sum(list1: List<String>, list3: List<Int>, list12: List<String>): Int {
    return list12.sumOf { name -> list1.indexOf(name).let { if (it >= 0) list3[it] else 0 } }
}

private fun findPerson(list1: List<String>, list2: List<String?>, list3: List<Int>, list5: List<Int>): String {
    var mincount = list3.maxOrNull() ?: 0
    var imin1 = list3.indexOf(list3.maxOrNull() ?: 0)
    var imin2 = list5.indexOf(list5.maxOrNull() ?: 0)
    var shiftmin = list5.maxOrNull() ?: 0

    for (i3 in list3.indices) {
        if (list3[i3] < mincount && list3[i3] > 0 && containsSubString(list2, list1[i3])) {
            imin1 = i3
            mincount = list3[i3]
        }
        if (list5[i3] < shiftmin && containsSubString(list2, list1[i3])) {
            imin2 = i3
            shiftmin = list5[i3]
        }
    }

    if (imin1 == imin2 && list5[imin1] == shiftmin) return list1[imin1]

    var maxnum = list3.maxOrNull() ?: 0
    var irequired = 0
    for (i3 in list3.indices) {
        if (list5[i3] == shiftmin && list3[i3] < maxnum && list3[i3] > 0 && containsSubString(list2, list1[i3])) {
            maxnum = list3[i3]
            irequired = i3
        } else if (list5[i3] == shiftmin && list3[i3] == maxnum && list3[i3] > 0 && containsSubString(list2, list1[i3])) {
            irequired = i3
        }
    }
    return list1[irequired]
}

// ========== Constraint Checkers ==========

private fun condition882(
    m2: List<List<List<String?>>>,
    arrayList21: List<List<String>>,
    list4: List<String>,
    person: String,
    cell: Int
): Boolean {
    val mCell = list4[cell]
    val i = mCell[0].digitToInt()
    val j = mCell[1].digitToInt()

    for (z in m2.indices) {
        when (j) {
            0 -> {
                if (i > 0) m2[z][i - 1][2]?.let { if (it.contains(person)) return false }
                m2[z][i][1]?.let { if (it.contains(person)) return false }
                if (mCell == "00") m2[z][6][1]?.let { if (it.contains(person)) return false }
            }
            2 -> {
                m2[z][i][1]?.let { if (it.contains(person)) return false }
                if (i < 6) m2[z][i + 1][0]?.let { if (it.contains(person)) return false }
                if (mCell == "62") m2[z][6][1]?.let { if (it.contains(person)) return false }
            }
            else -> {
                m2[z][i][0]?.let { if (it.contains(person)) return false }
                m2[z][i][2]?.let { if (it.contains(person)) return false }
            }
        }
    }

    for (list21 in arrayList21) {
        for (k in list21.indices) {
            if (list21[k].contains(person)) {
                val kcell = list4[k]
                if (mCell == "00" && (kcell == "01" || kcell == "61")) return false
                if (mCell == "62" && kcell == "61") return false
                if (j == 0 && (kcell == cellKey(i - 1, 2) || kcell == cellKey(i, 1))) return false
                if (j == 2 && (kcell == cellKey(i, 1) || kcell == cellKey(i + 1, 0))) return false
                if (kcell == cellKey(i, j - 1) || kcell == cellKey(i, j + 1)) return false
                if (kcell == mCell) return false
            }
        }
    }
    return true
}

private fun condition88(
    m2: List<List<List<String?>>>,
    arrayList21: List<List<String>>,
    list4: List<String>,
    person: String,
    cell: Int
): Boolean {
    val mcell = list4[cell]
    val i = mcell[0].digitToInt()
    val j = mcell[1].digitToInt()

    for (z in m2.indices) {
        if (mcell == "00") {
            if (m2[z][0][1] == person) return false
            if (m2[z][6][1] == person) return false
        }
        if (mcell == "62") {
            if (m2[z][6][1] == person) return false
        }
        when (j) {
            0 -> {
                if (i > 0 && m2[z][i - 1][2] == person) return false
                if (m2[z][i][1] == person) return false
            }
            2 -> {
                if (m2[z][i][1] == person) return false
                if (i < 6 && m2[z][i + 1][0] == person) return false
            }
            else -> {
                if (m2[z][i][0] == person) return false
                if (m2[z][i][2] == person) return false
            }
        }
    }

    for (list21 in arrayList21) {
        for (k in list21.indices) {
            if (list21[k] == person) {
                val kcell = list4[k]
                if (mcell == "00" && (kcell == "01" || kcell == "61")) return false
                if (mcell == "62" && kcell == "61") return false
                if (j == 0 && (kcell == cellKey(i - 1, 2) || kcell == cellKey(i, 1))) return false
                if (j == 2 && (kcell == cellKey(i, 1) || kcell == cellKey(i + 1, 0))) return false
                if (kcell == cellKey(i, j - 1) || kcell == cellKey(i, j + 1)) return false
                if (kcell == mcell) return false
            }
        }
    }
    return true
}

private fun findCell(
    list1: List<String>, list2: MutableList<String?>, list3: List<Int>,
    person: String, itempMin1: Int, list12Min1: List<String>,
    arrayListMat2: List<List<List<String?>>>, list21Array: List<List<String>>,
    list4: List<String>, stations: List<StationConfig>
): Pair<Int, List<String>> {
    var itempMin = itempMin1
    var list12Min = list12Min1

    var itemp = 0
    while (itemp < list2.size) {
        val cell = list2[itemp]
        if (cell != null && cell.contains(person)) {
            list12Min = extractNames(cell)
            itempMin = itemp
            break
        }
        itemp++
    }

    var sumMin = list12Sum(list1, list3, list12Min)
    itemp = 0
    while (itemp < list2.size) {
        val current = list2[itemp]
        while (current != null && current.contains(person) && itemp < list2.size - 1) {
            itemp++
        }
        val cell = list2.getOrNull(itemp)
        if (cell == null) { itemp++; continue }

        if (commaCount(cell) > 1) {
            val list12 = extractNames(cell)
            val sum = list12Sum(list1, list3, list12)
            if (sum < sumMin) {
                var count = 0
                for (w in arrayListMat2.indices) {
                    val peopleInStation = stations[w].numOfPeople
                    if (peopleInStation > 1) {
                        if (condition882(arrayListMat2, list21Array, list4, person, itempMin)) count++
                    } else if (peopleInStation == 1) {
                        if (condition88(arrayListMat2, list21Array, list4, person, itempMin)) count++
                    }
                }
                if (count > 0) {
                    sumMin = sum
                    itempMin = itemp
                    list12Min = list12
                }
            }
        }
        itemp++
    }

    return Pair(itempMin, list12Min)
}

// ========== Core Action ==========

private fun action(
    list1: List<String>, list2: MutableList<String?>, list3: MutableList<Int>,
    list4: List<String>, list5: MutableList<Int>,
    arrayListMat2: List<List<List<String?>>>, stations: List<StationConfig>
): List<List<String>> {
    val list21Array = arrayListMat2.map {
        list2.map { "" }.toMutableList()
    }.toMutableList()

    var iTempMin = 0
    var list12Min: List<String> = emptyList()

    while (!isWithoutWords(list2)) {
        val person = findPerson(list1, list2, list3, list5)
        val (foundMin, foundList) = findCell(
            list1, list2, list3, person, iTempMin, list12Min,
            arrayListMat2, list21Array, list4, stations
        )
        iTempMin = foundMin
        list12Min = foundList

        val mcell = list4[iTempMin]
        val i = mcell[0].digitToInt()
        val j = mcell[1].digitToInt()

        var placed = false
        for (w in arrayListMat2.indices) {
            val peopleInStation = stations[w].numOfPeople
            if (peopleInStation > 1) {
                if (condition882(arrayListMat2, list21Array, list4, person, iTempMin) &&
                    commaCount(list21Array[w][iTempMin]) < peopleInStation &&
                    arrayListMat2[w][i][j] != null
                ) {
                    list21Array[w][iTempMin] = list21Array[w][iTempMin] + person
                    list2[iTempMin] = list2[iTempMin]?.replace(person, "") ?: ""
                    val pIdx = list1.indexOf(person)
                    list3[pIdx]--
                    list5[pIdx]++
                    placed = true
                    break
                }
            } else if (peopleInStation == 1) {
                if (condition88(arrayListMat2, list21Array, list4, person, iTempMin) &&
                    commaCount(list21Array[w][iTempMin]) < peopleInStation &&
                    arrayListMat2[w][i][j] != null &&
                    list5[list1.indexOf(person)] < 6
                ) {
                    list21Array[w][iTempMin] = list21Array[w][iTempMin] + person
                    list2[iTempMin] = list2[iTempMin]?.replace(person, "") ?: ""
                    val pIdx = list1.indexOf(person)
                    list3[pIdx]--
                    list5[pIdx]++
                    placed = true
                    break
                }
            }
        }

        if (!placed) {
            list2[iTempMin] = list2[iTempMin]?.replace(person, "") ?: ""
            list3[list1.indexOf(person)]--
        }
    }

    return list21Array
}

// ========== Organize Matrices ==========

private fun organizeMatrices(
    mat: List<List<String>>,
    arrayListMat2: MutableList<MutableList<MutableList<String?>>>,
    stations: List<StationConfig>
): List<List<List<String?>>> {
    val list1 = mutableListOf<String>()
    val list3 = mutableListOf<Int>()
    val list5 = mutableListOf<Int>()
    var count = 1

    while (count <= list1.size || count == 1) {
        val list2 = mutableListOf<String?>()
        val list4 = mutableListOf<String>()
        var iaction = 0

        for (i in 0 until 7) {
            for (j in 0 until 3) {
                if (count == 1) {
                    names(list1, list3, list5, mat[i][j])
                }
                if (commaCount(mat[i][j]) == count) {
                    list2.add(mat[i][j])
                    list4.add(cellKey(i, j))
                    iaction++
                }
            }
        }

        if (count >= 1 && iaction > 0) {
            split(list1, list2, list3)
            val list21Array = action(
                list1, list2, list3, list4, list5,
                arrayListMat2, stations
            )

            for (i1 in list4.indices) {
                val mcell = list4[i1]
                val i = mcell[0].digitToInt()
                val j = mcell[1].digitToInt()
                for (w in arrayListMat2.indices) {
                    arrayListMat2[w][i][j] = list21Array[w][i1]
                }
            }
        }
        count++
    }

    return arrayListMat2
}
