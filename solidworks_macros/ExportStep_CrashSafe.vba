' =========================================================================
' STEP EXPORT - CRASH-SAFE SURUM (SolidWorks 2014 uyumlu)
' Buyuk montaj (level-8) + zayif PC icin: resolve YOK, govde taramasi YOK,
' parcalar TEKER TEKER gorunmez acilip kapatilir, hata izole edilir.
' Kullanim: montaji LIGHTWEIGHT + Large Assembly Mode'da ac, makroyu calistir.
' Kaldigin yerden devam eder (SKIP_EXISTING_FILES = True).
' Varsayilan: sac parcalar (FlatPattern olanlar) atlanir, cunku onlarin DXF'i
' ayri makrodan cikiyor. Hepsini istersen SKIP_SHEETMETAL_PARTS = False yap.
' =========================================================================
Option Explicit

' --- AYARLAR ---
Const SKIP_EXISTING_FILES As Boolean = True
Const SKIP_SHEETMETAL_PARTS As Boolean = True
Const OUT_DIR_TEMPLATE As String = "STEP_EXPORT\"
Const STATUS_EVERY As Long = 5

Dim swApp As SldWorks.SldWorks
Dim gLog As Collection
Dim gOk As Long, gSkip As Long, gFail As Long, gSheet As Long
Dim gTotalInst As Long, gTotalKeys As Long ' ornek sayisi (tekrar dahil) / benzersiz dosya

Sub main()

    Set swApp = Application.SldWorks
    Set gLog = New Collection
    gOk = 0: gSkip = 0: gFail = 0: gSheet = 0: gTotalInst = 0: gTotalKeys = 0

    On Error GoTo catch_

    Dim swModel As SldWorks.ModelDoc2
    Set swModel = swApp.ActiveDoc

    If swModel Is Nothing Then
        Err.Raise vbError, "", "Once montaj veya parca dosyasini acin"
    End If

    If swModel.GetType() = swDocumentTypes_e.swDocASSEMBLY Then

        Dim swAssy As SldWorks.AssemblyDoc
        Set swAssy = swModel

        ' KRITIK: ResolveAll YOK. Montaj lightweight kalir.
        Dim keys As Object
        Set keys = CollectUniquePartKeys(swAssy)
        gTotalKeys = keys.Count ' benzersiz dosya sayisi

        If keys.Count = 0 Then
            swApp.SendMsgToUser2 "Islenecek parca bulunamadi.", _
                swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
            GoTo finally_
        End If

        Dim arrKeys As Variant
        arrKeys = keys.keys

        Dim i As Long
        For i = 0 To UBound(arrKeys)
            Dim vals As Variant
            vals = keys(arrKeys(i))
            ProcessOneFile swModel, CStr(vals(0)), CStr(vals(1))

            If (i + 1) Mod STATUS_EVERY = 0 Then
                DoEvents ' (2014'te status-bar API yok; sadece nefes aldir)
            End If
        Next i

    ElseIf swModel.GetType() = swDocumentTypes_e.swDocPART Then

        gTotalKeys = 1: gTotalInst = 1 ' tek dosya modu
        ExportCurrentPart swModel

    Else
        Err.Raise vbError, "", "Sadece montaj ve parca desteklenir"
    End If

    GoTo finally_

catch_:
    gLog.Add "[KRITIK] " & Err.Description
finally_:
    On Error Resume Next
    WriteLogFile swApp.ActiveDoc
    Dim msg As String
    msg = "Islem tamamlandi!" & vbCrLf & vbCrLf & _
        "- Taranan ornek / benzersiz dosya: " & gTotalInst & " / " & gTotalKeys & vbCrLf & _
        "- Olusturulan STEP: " & gOk & vbCrLf & _
        "- Zaten mevcut (Atlandi): " & gSkip & vbCrLf & _
        "- Sac parca (Atlandi): " & gSheet & vbCrLf & _
        "- Hatali: " & gFail
    If gFail > 0 Or gLog.Count > 0 Then
        msg = msg & vbCrLf & vbCrLf & "Detay: montaj klasorunde export_raporu_step.txt"
    End If
    swApp.SendMsgToUser2 msg, swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
    Set gLog = Nothing

End Sub

' --- FAZ 1: dosya acmadan benzersiz parca listesi (recursive, cozunmesiz) ---
' GetComponents(False) lightweight alt montajlarin icini VERMEZ. Agactan inilir:
' GetComponents(True) + GetChildren. Govdeye dokunulmaz, resolve YOK. Dongu korumasi: visited.
Function CollectUniquePartKeys(assy As SldWorks.AssemblyDoc) As Object

    Dim dict As Object
    Set dict = CreateObject("Scripting.Dictionary")
    dict.CompareMode = 1 ' vbTextCompare

    Dim visited As Object
    Set visited = CreateObject("Scripting.Dictionary")
    visited.CompareMode = 1

    Dim vTop As Variant
    vTop = assy.GetComponents(True) ' sadece en ust seviye

    If Not IsEmpty(vTop) Then
        Dim i As Long
        Dim swTop As SldWorks.Component2
        For i = 0 To UBound(vTop)
            Set swTop = vTop(i)
            Call CollectComp(swTop, dict, visited)
        Next i
    End If

    Set CollectUniquePartKeys = dict

End Function

' Tek bileseni isle: parcaysa listeye ekle, montajsa cocuklara in (recursive, cozunmesiz).
Sub CollectComp(swComp As SldWorks.Component2, dict As Object, visited As Object)
    On Error Resume Next ' tek bozuk bilesen butunu durdurmasin
    If swComp Is Nothing Then Exit Sub
    If swComp.IsSuppressed() Then Exit Sub
    Dim p As String
    p = swComp.GetPathName() ' cozunmeden path verir
    If p = "" Then Exit Sub
    If UCase(Right(p, 6)) = "SLDPRT" Then
        gTotalInst = gTotalInst + 1 ' her ornegi say (tekrar dahil)
        Dim c As String
        c = swComp.ReferencedConfiguration
        Dim k As String
        k = p & "||" & UCase(c)
        If Not dict.Exists(k) Then
            dict.Add k, Array(p, c)
        End If
    ElseIf UCase(Right(p, 6)) = "SLDASM" Then
        Dim ak As String
        ak = p & "||" & UCase(swComp.ReferencedConfiguration)
        If visited.Exists(ak) Then Exit Sub ' dongu/tekrar korumasi
        visited.Add ak, 1
        Dim vCh As Variant
        vCh = swComp.GetChildren ' lightweight icin de cocuklari verir, cozmez
        If Not IsEmpty(vCh) Then
            Dim j As Long
            Dim swCh As SldWorks.Component2
            For j = 0 To UBound(vCh)
                Set swCh = vCh(j)
                Call CollectComp(swCh, dict, visited)
            Next j
        End If
    End If
End Sub

' --- FAZ 2: tek dosya ---
Sub ProcessOneFile(rootModel As SldWorks.ModelDoc2, partPath As String, conf As String)

    On Error GoTo fail_

    Dim swPartModel As SldWorks.ModelDoc2
    Set swPartModel = Nothing
    Dim openedHere As Boolean: openedHere = False

    On Error Resume Next
    Set swPartModel = swApp.GetOpenDocumentByName(partPath)
    On Error GoTo fail_

    If swPartModel Is Nothing Then
        Dim errVal As Long, warnVal As Long
        On Error Resume Next
        swApp.DocumentVisible False, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        Set swPartModel = swApp.OpenDoc6(partPath, swDocumentTypes_e.swDocPART, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            conf, errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        If Not swPartModel Is Nothing Then openedHere = True
    End If

    If swPartModel Is Nothing Then
        gFail = gFail + 1
        gLog.Add "[ACILAMADI] " & partPath & " (" & conf & ")"
        Exit Sub
    End If

    ExportStepForModel rootModel, swPartModel, conf, openedHere

    If openedHere Then
        On Error Resume Next
        swApp.CloseDoc swPartModel.GetTitle()
        On Error GoTo fail_
    End If
    Set swPartModel = Nothing
    Exit Sub

fail_:
    gFail = gFail + 1
    gLog.Add "[HATA] " & partPath & " (" & conf & "): " & Err.Description
    On Error Resume Next
    If openedHere Then
        If Not swPartModel Is Nothing Then swApp.CloseDoc swPartModel.GetTitle()
    End If
    swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
    Set swPartModel = Nothing

End Sub

' Tek parca modunda (aktif dokuman parca ise)
Sub ExportCurrentPart(swModel As SldWorks.ModelDoc2)
    On Error GoTo fail_
    Dim conf As String
    conf = swModel.ConfigurationManager.ActiveConfiguration.Name
    ExportStepForModel swModel, swModel, conf, False
    Exit Sub
fail_:
    gFail = gFail + 1
    gLog.Add "[HATA] " & swModel.GetPathName() & ": " & Err.Description
End Sub

Sub ExportStepForModel(rootModel As SldWorks.ModelDoc2, sheetModel As SldWorks.ModelDoc2, _
                       conf As String, ByVal openedHere As Boolean)

    On Error GoTo fail_

    ' Sac eleme: FlatPattern unsuru varsa DXF'lik parca, STEP'te atla
    If SKIP_SHEETMETAL_PARTS Then
        If HasFlatPattern(sheetModel) Then
            gSheet = gSheet + 1
            Exit Sub
        End If
    End If

    Dim outFile As String
    outFile = ComposeStepPath(rootModel, sheetModel, conf)

    If SKIP_EXISTING_FILES And FileExists(outFile) Then
        gSkip = gSkip + 1
        Exit Sub
    End If

    CreateDirectories Left(outFile, InStrRev(outFile, "\"))

    ' Dogru konfigurasyonu aktif et (gerekiyorsa), rebuild YOK
    Dim curConf As String: curConf = ""
    Dim switched As Boolean: switched = False
    On Error Resume Next
    curConf = sheetModel.ConfigurationManager.ActiveConfiguration.Name
    On Error GoTo fail_

    If curConf <> conf And conf <> "" Then
        swApp.ActivateDoc3 sheetModel.GetPathName(), False, _
            swRebuildOnActivation_e.swDontRebuildActiveDoc, 0
        If False <> sheetModel.ShowConfiguration2(conf) Then
            switched = True
        End If
    End If

    Dim errs As Long, warns As Long
    Dim okSave As Boolean
    ' 0 = swSaveAsCurrentVersion, 1 = swSaveAsOptions_Silent
    okSave = sheetModel.Extension.SaveAs(outFile, 0, 1, Nothing, errs, warns)

    If okSave And FileExists(outFile) Then
        gOk = gOk + 1
    Else
        gFail = gFail + 1
        gLog.Add "[STEP-HATA] " & outFile & " (err=" & errs & ")"
        On Error Resume Next
        Kill outFile
        On Error GoTo fail_
    End If

    ' Odunc alinan dokumanin konfigurasyonunu geri al (kendimiz actiysak kapatacagiz, gerek yok)
    If switched And False = openedHere And curConf <> "" Then
        On Error Resume Next
        sheetModel.ShowConfiguration2 curConf
        On Error GoTo fail_
    End If
    Exit Sub

fail_:
    gFail = gFail + 1
    gLog.Add "[HATA] " & sheetModel.GetPathName() & " (" & conf & "): " & Err.Description

End Sub

' Hizli sac kontrolu: unsur agacinda FlatPattern var mi (rebuild yok, govde yok)
Function HasFlatPattern(model As SldWorks.ModelDoc2) As Boolean
    On Error Resume Next
    HasFlatPattern = False
    Dim f As SldWorks.Feature
    Set f = model.FirstFeature()
    Do While Not f Is Nothing
        If HasFlatRecursive(f) Then
            HasFlatPattern = True
            Exit Function
        End If
        Set f = f.GetNextFeature()
    Loop
End Function

Function HasFlatRecursive(feat As SldWorks.Feature) As Boolean
    On Error Resume Next
    HasFlatRecursive = False
    If feat.GetTypeName2() = "FlatPattern" Then
        HasFlatRecursive = True
        Exit Function
    End If
    Dim s As SldWorks.Feature
    Set s = feat.GetFirstSubFeature()
    While Not s Is Nothing
        If HasFlatRecursive(s) Then
            HasFlatRecursive = True
            Exit Function
        End If
        Set s = s.GetNextSubFeature()
    Wend
End Function

Function ComposeStepPath(rootModel As SldWorks.ModelDoc2, sheetModel As SldWorks.ModelDoc2, conf As String) As String
    Dim baseName As String
    baseName = GetFileNameWithoutExtension(sheetModel.GetPathName())
    baseName = CleanName(baseName)
    ' Varsayilan disi konfigurasyonda dosya adina ekle (ustune yazmayi onler)
    If conf <> "" And LCase(conf) <> "default" And LCase(conf) <> "varsayılan" Then
        baseName = baseName & "_" & CleanName(conf)
    End If
    Dim rootDir As String
    rootDir = GetRootDir(rootModel, sheetModel)
    ComposeStepPath = rootDir & OUT_DIR_TEMPLATE & baseName & ".step"
End Function

Function GetRootDir(rootModel As SldWorks.ModelDoc2, fallbackModel As SldWorks.ModelDoc2) As String
    Dim p As String
    On Error Resume Next
    p = rootModel.GetPathName()
    If p = "" Then p = fallbackModel.GetPathName()
    GetRootDir = Left(p, InStrRev(p, "\"))
End Function

Function GetFileNameWithoutExtension(path As String) As String
    Dim s As Long, e As Long
    s = InStrRev(path, "\") + 1
    e = InStrRev(path, ".")
    If e <= s Then
        GetFileNameWithoutExtension = Mid(path, s)
    Else
        GetFileNameWithoutExtension = Mid(path, s, e - s)
    End If
End Function

Function CleanName(n As String) As String
    Dim invalidSymbols As Variant
    invalidSymbols = Array("/", "\", ":", "*", "?", """", "<", ">", "|")
    Dim i As Long, r As String
    r = n
    For i = 0 To UBound(invalidSymbols)
        r = Replace(r, CStr(invalidSymbols(i)), "_")
    Next i
    CleanName = Trim(r)
End Function

Function FileExists(filePath As String) As Boolean
    On Error Resume Next
    FileExists = (Dir(filePath) <> "")
End Function

Sub CreateDirectories(path As String)
    Dim fso As Object
    Set fso = CreateObject("Scripting.FileSystemObject")
    If fso.FolderExists(path) Then Exit Sub
    CreateDirectories fso.GetParentFolderName(path)
    fso.CreateFolder path
End Sub

Sub WriteLogFile(activeModel As SldWorks.ModelDoc2)
    On Error Resume Next
    If gLog Is Nothing Then Exit Sub
    If gLog.Count = 0 And gFail = 0 Then Exit Sub
    If activeModel Is Nothing Then Exit Sub
    Dim asmPath As String
    asmPath = activeModel.GetPathName()
    If asmPath = "" Then Exit Sub
    Dim dirP As String
    dirP = Left(asmPath, InStrRev(asmPath, "\") - 1)
    Dim fso As Object
    Set fso = CreateObject("Scripting.FileSystemObject")
    Dim ts As Object
    Set ts = fso.OpenTextFile(dirP & "\export_raporu_step.txt", 8, True)
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "STEP EXPORT RAPORU - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "Ornek: " & gTotalInst & " | Dosya: " & gTotalKeys & " | OK: " & gOk & " | Mevcut-Atla: " & gSkip & " | Sac-Atla: " & gSheet & " | Hata: " & gFail
    ts.WriteLine "========================================================"
    Dim j As Long
    For j = 1 To gLog.Count
        ts.WriteLine gLog(j)
    Next j
    ts.WriteLine ""
    ts.Close
End Sub
