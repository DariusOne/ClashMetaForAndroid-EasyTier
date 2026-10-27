package com.github.kr328.clash.service.easytier

import android.os.IBinder

internal object NativeMeshProtocol {
    const val DESCRIPTOR = "com.github.kr328.clash.native-mesh.v1"
    const val START = IBinder.FIRST_CALL_TRANSACTION
    const val ATTACH = START + 1
    const val SNAPSHOT = START + 2
    const val STOP = START + 3
    const val MAX_PROFILE_BYTES = 1024 * 1024
}
