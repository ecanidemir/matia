' =========================================================================
' MIRROR TEST - Left/Right konfigli sac parcalar (SADECE test, ana makroda yok)
' Kodlar: M3K2LN12 (81), M3E2LN05 (78), M3H2LN13 (41) - adet sac_liste.txt'ten okunur.
' Mantik: dosyadaki HER konfigurasyon tek tek aktive edilir, o konfigin
' secilebilir FlatPattern unsurlari ayri DXF'e yazilir:
'   MirrorTest\<Malzeme>\<Kalinlik>\<KOD>_<Konf>_<ADET>_Adet.dxf
' Secilemeyen (diger konfige ait/suppressed) flat atlanir + loglanir.
' Konfig degisimi bellege yazilmaz (read-only acilis + ClearDirtyFlag + kapatma).
' SolidWorks 2014 uyumu: DocumentVisible 2 arguman, tek-argumanli Get,
' Call'suz parantezli Function-statement yok, SetSaveFlag icin CallByName.
' =========================================================================
Option Explicit

Const BASE_DIR As String = "D:\Ortak Drive'lar\Matia Mobility\2000_TECHNICAL\2300_3D_CAD\2310_TekRMD_Sldwrks"
Const LIST_NAME As String = "sac_liste.txt"
Const OUT_ROOT As String = "Lazer_Kesim&Bukum_13102026\MirrorTest"
Const LOG_NAME As String = "export_raporu_mirror_test.txt"
Const FLAT_OPTS As Long = 1 ' ExportFlatPatternGeometry (ana makro ile ayni)

Dim swApp As SldWorks.SldWorks
Dim gFso As Object
Dim gLog As Collection
Dim gLogPath As String

Sub LogLine(msg As String)
    On Error Resume Next
    If Not gLog Is Nothing Then gLog.Add msg
    If gLogPath <> "" Then
        If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
        Dim ts As Object
        Set ts = gFso.OpenTextFile(gLogPath, 8, True)
        ts.WriteLine msg
        ts.Close
    End If
End Sub

Sub main()
    Set swApp = Application.SldWorks
    Set gFso = CreateObject("Scripting.FileSystemObject")
    Set gLog = New Collection
    gLogPath = BASE_DIR & "\" & LOG_NAME
    On Error GoTo catch_
    Dim ts0 As Object
    Set ts0 = gFso.OpenTextFile(gLogPath, 8, True)
    ts0.WriteLine ""
    ts0.WriteLine "=== MIRROR TEST BASLADI - " & Format(Now, "yyyy-MM-dd HH:mm:ss") & " ==="
    ts0.Close
    On Error GoTo catch_
    Dim codes As Variant
    codes = Array("M3K2LN12", "M3E2LN05", "M3H2LN13")
    Dim i As Long
    For i = 0 To UBound(codes)
        ProcessMirror CStr(codes(i)), GetQtyFor(CStr(codes(i)))
    Next i
    GoTo finally_
catch_:
    LogLine "[KRITIK] " & Err.Description
finally_:
    On Error Resume Next
    Dim ts As Object
    Set ts = gFso.OpenTextFile(gLogPath, 8, True)
    ts.WriteLine "=== MIRROR TEST BITTI - " & Format(Now, "yyyy-MM-dd HH:mm:ss") & " ==="
    Dim j As Long
    For j = 1 To gLog.Count
        ts.WriteLine gLog(j)
    Next j
    ts.WriteLine ""
    ts.Close
    swApp.SendMsgToUser2 "Mirror test bitti. Detay: " & gLogPath, _
        swMessageBoxIcon_e.swMbInformation, swMessageBoxBtn_e.swMbOk
    Set gLog = Nothing
End Sub

' sac_liste.txt'ten kodun adetini bulur (bulamazsa "" doner).
Function GetQtyFor(code As String) As String
    GetQtyFor = ""
    On Error Resume Next
    Dim ts As Object
    Set ts = gFso.OpenTextFile(BASE_DIR & "\" & LIST_NAME, 1, False)
    If ts Is Nothing Then Exit Function
    Dim raw As String
    raw = ts.ReadAll()
    ts.Close
    Dim arr As Variant
    arr = Split(raw, vbCrLf)
    Dim i As Long
    For i = 0 To UBound(arr)
        Dim ln As String
        ln = Trim(CStr(arr(i)))
        If UCase(ln) Like UCase(code) & ",*" Then
            GetQtyFor = Trim(Mid(ln, Len(code) + 2))
            Exit Function
        End If
    Next i
End Function

' MirrorTest agacinda bu kod+adet icin uretilmis DXF var mi? (crash-resume)
Function MirrorDone(code As String, qty As String) As Boolean
    MirrorDone = False
    On Error Resume Next
    Dim root As String
    root = BASE_DIR & "\" & OUT_ROOT
    If Not gFso.FolderExists(root) Then Exit Function
    MirrorDone = FindFileRec(gFso.GetFolder(root), code & "_" & qty & "_Adet.dxf")
End Function

Function FindFileRec(fld As Object, fname As String) As Boolean
    FindFileRec = False
    On Error Resume Next
    Dim f As Object
    For Each f In fld.Files
        If UCase(f.Name) = UCase(fname) Then
            FindFileRec = True
            Exit Function
        End If
    Next f
    Dim s As Object
    For Each s In fld.SubFolders
        If FindFileRec(s, fname) Then
            FindFileRec = True
            Exit Function
        End If
    Next s
End Function

Sub ProcessMirror(code As String, qty As String)
    On Error GoTo fail_
    Dim partPath As String
    partPath = BASE_DIR & "\" & code & ".sldprt"
    LogLine "[DOSYA] " & code & " [adet:" & qty & "]"
    If Not gFso.FileExists(partPath) Then
        LogLine "[YOK] " & partPath
        Exit Sub
    End If
    If MirrorDone(code, qty) Then
        LogLine "[MEVCUT] " & code & " (MirrorTest'te mevcut, atlandi)"
        Exit Sub
    End If
    Dim swModel As SldWorks.ModelDoc2
    Set swModel = Nothing
    On Error Resume Next
    Set swModel = swApp.GetOpenDocumentByName(partPath)
    On Error GoTo fail_
    Dim openedHere As Boolean: openedHere = False
    If swModel Is Nothing Then
        Dim errVal As Long, warnVal As Long
        On Error Resume Next
        swApp.DocumentVisible False, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        Set swModel = swApp.OpenDoc6(partPath, swDocumentTypes_e.swDocPART, _
            swOpenDocOptions_e.swOpenDocOptions_Silent Or swOpenDocOptions_e.swOpenDocOptions_ReadOnly, _
            "", errVal, warnVal)
        On Error Resume Next
        swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
        On Error GoTo fail_
        If Not swModel Is Nothing Then openedHere = True
    End If
    If swModel Is Nothing Then
        LogLine "[ACILAMADI] " & partPath & " err=" & errVal
        Exit Sub
    End If
    Dim swPart As SldWorks.PartDoc
    Set swPart = swModel
    ' Konfig degisimi gorunmez belgede 2014'u deviriyor -> once gorunur yap + aktive et.
    Dim wasHidden As Boolean: wasHidden = False
    On Error Resume Next
    If False = swModel.Visible Then
        wasHidden = True
        swModel.Visible = True
    End If
    swApp.ActivateDoc3 swModel.GetPathName(), False, _
        swRebuildOnActivation_e.swDontRebuildActiveDoc, 0
    On Error GoTo fail_
    Dim origConf As String: origConf = ""
    On Error Resume Next
    origConf = swModel.ConfigurationManager.ActiveConfiguration.Name
    On Error GoTo fail_
    LogLine "[KONFIGLER] " & code & " aktif=" & origConf
    Dim vConfs As Variant
    vConfs = swModel.GetConfigurationNames
    If IsEmpty(vConfs) Then
        LogLine "[KONFIG-YOK] " & code
        GoTo cleanup_
    End If
    Dim ci As Long
    For ci = 0 To UBound(vConfs)
        If ExportOneConfig(swModel, swPart, code, qty, CStr(vConfs(ci))) Then
            LogLine "[TEK-FLAT] " & code & " <- " & CStr(vConfs(ci)) & " (diger konfigler atlandi)"
            Exit For
        End If
    Next ci
    GoTo cleanup_
fail_:
    LogLine "[HATA] " & code & ": " & Err.Description
    On Error Resume Next
cleanup_:
    On Error Resume Next
    If False = openedHere Then
        If origConf <> "" Then swModel.ShowConfiguration2 origConf
        If wasHidden Then swModel.Visible = False
    End If
    If openedHere Then
        ClearDirtyFlag swModel
        Call CloseDocVerified(partPath, swModel.GetTitle())
    End If
    swApp.DocumentVisible True, swDocumentTypes_e.swDocPART
    Set swPart = Nothing
    Set swModel = Nothing
End Sub

' Tek konfigi aktive edip secilebilir flat'leri ayri DXF'lere yazar.
Function ExportOneConfig(swModel As SldWorks.ModelDoc2, swPart As SldWorks.PartDoc, _
                    code As String, qty As String, confName As String) As Boolean
    ExportOneConfig = False
    On Error GoTo fail_
    If False = swModel.ShowConfiguration2(confName) Then
        LogLine "[CONF-ACILAMADI] " & code & " (" & confName & ")"
        Exit Function
    End If
    Dim vFlats As Variant
    vFlats = CollectFlats(swModel)
    If IsEmpty(vFlats) Then
        LogLine "[FLAT-YOK] " & code & " (" & confName & ")"
        Exit Function
    End If
    Dim mat As String, thk As String
    mat = GetModelProp(swModel, confName, "Malzeme")
    thk = GetCutProp(swModel, "Sac Levha Kalınlığı")
    If thk = "" Then thk = GetThicknessMM(swModel)
    If mat = "" Then mat = "NoMaterial"
    If thk = "" Then thk = "NoThk"
    Dim fi As Long
    For fi = 0 To UBound(vFlats)
        Dim swF As SldWorks.Feature
        Set swF = vFlats(fi)
        If False = swF.Select2(False, -1) Then
            LogLine "[ATLA-suppressed] " & code & " (" & confName & ") flat=" & swF.Name
        Else
            Dim outFile As String
            outFile = BASE_DIR & "\" & OUT_ROOT & "\" & mat & "\" & thk & "\" & _
                code & "_" & qty & "_Adet.dxf"
            outFile = SanitizePath(outFile)
            CreateDirs Left(outFile, InStrRev(outFile, "\"))
            Dim ok As Boolean: ok = False
            On Error Resume Next
            If False <> swPart.ExportToDWG2(outFile, swModel.GetPathName(), _
                    swExportToDWG_e.swExportToDWG_ExportSheetMetal, True, Empty, False, False, FLAT_OPTS, Empty) Then
                ok = True
            End If
            On Error GoTo fail_
            If False = ok Then
                On Error Resume Next
                If False <> swPart.ExportFlatPatternView(outFile, FLAT_OPTS) Then
                    If gFso.FileExists(outFile) Then ok = True
                End If
                On Error GoTo fail_
            End If
            If ok Then
                LogLine "[DXF-OK] " & outFile
                ExportOneConfig = True
                Set swF = Nothing
                Exit Function
            Else
                LogLine "[EXPORT-HATA] " & outFile
                On Error Resume Next
                Kill outFile
                On Error GoTo fail_
            End If
        End If
        Set swF = Nothing
    Next fi
    Exit Function
fail_:
    LogLine "[HATA] " & code & " (" & confName & "): " & Err.Description
End Function

' Modeldeki tum FlatPattern unsurlarini toplar (alt unsurlar dahil).
Function CollectFlats(model As SldWorks.ModelDoc2) As Variant
    Dim arr() As SldWorks.Feature
    Dim has As Boolean: has = False
    Dim swF As SldWorks.Feature
    Set swF = model.FirstFeature()
    Do While Not swF Is Nothing
        CollectFlatRec swF, arr, has
        Set swF = swF.GetNextFeature()
    Loop
    If Not has Then CollectFlats = Empty Else CollectFlats = arr
End Function

Sub CollectFlatRec(feat As SldWorks.Feature, arr() As SldWorks.Feature, ByRef has As Boolean)
    On Error Resume Next
    If feat.GetTypeName2() = "FlatPattern" Then
        If Not has Then
            ReDim arr(0): Set arr(0) = feat: has = True
        Else
            ReDim Preserve arr(UBound(arr) + 1): Set arr(UBound(arr)) = feat
        End If
    End If
    Dim swS As SldWorks.Feature
    Set swS = feat.GetFirstSubFeature()
    Do While Not swS Is Nothing
        CollectFlatRec swS, arr, has
        Set swS = swS.GetNextSubFeature()
    Loop
End Sub

Function GetModelProp(model As SldWorks.ModelDoc2, confName As String, prp As String) As String
    Dim v As String
    On Error Resume Next
    v = model.Extension.CustomPropertyManager(confName).Get(prp)
    If v = "" Or InStr(v, "@@@") > 0 Then
        v = model.Extension.CustomPropertyManager("").Get(prp)
    End If
    If InStr(v, "@@@") > 0 Then v = ""
    GetModelProp = v
End Function

' Ilk cut-list klasorunden kalinlik ozelligini okur (cozulememis baglanti = "").
Function GetCutProp(model As SldWorks.ModelDoc2, prpName As String) As String
    GetCutProp = ""
    On Error Resume Next
    Dim swF As SldWorks.Feature
    Set swF = model.FirstFeature()
    Do While Not swF Is Nothing
        If swF.GetTypeName2() = "CutListFolder" Then
            Dim mgr As SldWorks.CustomPropertyManager
            Set mgr = swF.CustomPropertyManager
            If Not mgr Is Nothing Then
                Dim rv As String
                rv = mgr.Get(prpName)
                If rv <> "" And InStr(rv, "@@@") = 0 Then
                    GetCutProp = rv
                    Exit Function
                End If
            End If
        End If
        Set swF = swF.GetNextFeature()
    Loop
End Function

' Sac-Levha unsurundan gercek kalinlik (mm).
Function GetThicknessMM(model As SldWorks.ModelDoc2) As String
    On Error Resume Next
    GetThicknessMM = ""
    Dim swF As SldWorks.Feature
    Set swF = model.FirstFeature()
    Do While Not swF Is Nothing
        If LCase(swF.GetTypeName2()) = "sheetmetal" Then
            Dim smd As SldWorks.SheetMetalFeatureData
            Set smd = swF.GetDefinition()
            If Not smd Is Nothing Then
                Dim tmm As Double
                tmm = smd.Thickness * 1000#
                If Abs(tmm - Round(tmm)) < 0.001 Then
                    GetThicknessMM = CStr(CLng(Round(tmm)))
                Else
                    GetThicknessMM = CStr(Round(tmm * 100#) / 100#)
                End If
                Exit Function
            End If
        End If
        Set swF = swF.GetNextFeature()
    Loop
End Function

Function Sanitize(s As String) As String
    Dim r As String: r = s
    Dim bad As Variant
    bad = Array("/", ":", "*", "?", """", "<", ">", "|", "@")
    Dim i As Long
    For i = 0 To UBound(bad)
        r = Replace(r, CStr(bad(i)), "_")
    Next i
    Sanitize = Trim(r)
End Function

Function SanitizePath(p As String) As String
    Dim drive As String, rest As String
    If Mid(p, 2, 1) = ":" Then
        drive = Left(p, 3): rest = Mid(p, 4)
    Else
        drive = "": rest = p
    End If
    Dim bad As Variant
    bad = Array("/", ":", "*", "?", """", "<", ">", "|")
    Dim i As Long
    For i = 0 To UBound(bad)
        rest = Replace(rest, CStr(bad(i)), "_")
    Next i
    SanitizePath = drive + rest
End Function

Sub CreateDirs(p As String)
    If gFso Is Nothing Then Set gFso = CreateObject("Scripting.FileSystemObject")
    If gFso.FolderExists(p) Then Exit Sub
    CreateDirs gFso.GetParentFolderName(p)
    gFso.CreateFolder p
End Sub

Sub ClearDirtyFlag(model As SldWorks.ModelDoc2)
    On Error Resume Next
    Call CallByName(model, "SetSaveFlag", VbMethod, False)
    If Err.Number <> 0 Then
        Err.Clear
        CallByName model, "SetSaveFlag", VbLet, False
    End If
End Sub

Sub CloseDocVerified(docPath As String, docTitle As String)
    On Error Resume Next
    If Right(docTitle, 2) = " *" Then docTitle = Left(docTitle, Len(docTitle) - 2)
    swApp.CloseDoc docTitle
    Dim still As Object
    Set still = swApp.GetOpenDocumentByName(docPath)
    If Not still Is Nothing Then LogLine "[KAPAT-HATA] " & docPath
End Sub
