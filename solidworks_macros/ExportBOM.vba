' ******************************************************************************
' SolidWorks Multi-Level BOM & Custom Property Export Macro
' ******************************************************************************
'
' AMAC:
'   SolidWorks montaj dosyalarindan BOM verisini CSV formatinda disa aktarir.
'   9 sutunluk CSV ciktisi: Parent, Child, Miktar + 6 Custom Property
'
' CUSTOM PROPERTIES:
'   uretim_sekli, malzeme, malzeme_ebat, alt_kod, revizyon, tarih
'
' CIKTI: Masaustune {MontajAdi}_BOM.csv dosyasi olusturulur.
' ******************************************************************************

Option Explicit

' ============================================================================
' CUSTOM PROPERTY SABITLERI
' ============================================================================
Const CP_URETIM_SEKLI As String = "uretim_sekli"
Const CP_MALZEME As String = "malzeme"
Const CP_MALZEME_EBAT As String = "malzeme_ebat"
Const CP_ALT_KOD As String = "alt_kod"
Const CP_REVIZYON As String = "revizyon"
Const CP_TARIH As String = "tarih"

' ============================================================================
' GLOBAL DEGISKENLER
' ============================================================================
Dim swApp As Object
Dim swModel As Object
Dim swConf As Object
Dim swRootComp As Object
Dim bomDict As Object           ' Scripting.Dictionary - BOM satirlari
Dim qtyDict As Object           ' Scripting.Dictionary - Miktar sayaci
Dim modelCache As Object        ' Scripting.Dictionary - Model referans cache
Dim totalComponents As Long     ' Toplam islenen bilesen sayisi
Dim skippedComponents As Long   ' Atlanan bilesen sayisi
Dim errorLog As String          ' Hata/uyari loglari
Dim suppressedDict As Object    ' Scripting.Dictionary - Suppress edilmis bilesen isimleri
Dim traversedSubAsm As Object   ' Scripting.Dictionary - Zaten traverse edilmis alt-montajlar

' ============================================================================
' ANA GIRIS NOKTASI
' ============================================================================
Sub main()
    On Error GoTo ErrorHandler
    
    Dim startTime As Double
    startTime = Timer
    
    ' --- BASLANGIC KONTROLLER ---
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    
    If swModel Is Nothing Then
        MsgBox "Lütfen bir montaj dosyasi açin.", vbCritical, "Hata"
        Exit Sub
    End If
    
    If swModel.GetType <> 2 Then  ' 2 = swDocASSEMBLY
        MsgBox "Bu makro sadece montaj dosyalarinda (*.SLDASM) çalisir.", vbCritical, "Hata"
        Exit Sub
    End If
    
    ' --- PERFORMANS: HAFIFLETILMIS PARCALARI COZUMLE ---
    Dim resolveResult As Long
    resolveResult = swModel.ResolveAllLightWeightComponents(False)
    
    ' --- PERFORMANS: GRAFIK GUNCELLEMEYI DURDUR ---
    Dim swModelView As Object
    Set swModelView = swModel.ActiveView
    If Not swModelView Is Nothing Then
        swModelView.EnableGraphicsUpdate = False
    End If
    
    ' --- DICTIONARY'LERI OLUSTUR ---
    Set bomDict = CreateObject("Scripting.Dictionary")
    Set qtyDict = CreateObject("Scripting.Dictionary")
    Set modelCache = CreateObject("Scripting.Dictionary")
    Set suppressedDict = CreateObject("Scripting.Dictionary")
    Set traversedSubAsm = CreateObject("Scripting.Dictionary")
    totalComponents = 0
    skippedComponents = 0
    errorLog = ""
    
    ' --- KONFIGURASYON VE ROOT BILESEN ---
    Set swConf = swModel.GetActiveConfiguration
    Set swRootComp = swConf.GetRootComponent3(True)
    
    If swRootComp Is Nothing Then
        MsgBox "Kök bilesen (Root Component) alinamadi!", vbCritical, "Hata"
        GoTo Cleanup
    End If

    ' --- DOSYA YOLU ---
    Dim filePath As String
    Dim assemblyName As String
    assemblyName = GetFileNameWithoutExtension(swModel.GetTitle)
    filePath = CreateObject("WScript.Shell").SpecialFolders("Desktop") & "\" & assemblyName & "_BOM.csv"
    
    ' --- CSV BASLIK SATIRI ---
    Dim header As String
    header = "Üst Parça (Parent)"
    header = header & ";Alt Parça (Child)"
    header = header & ";Miktar"
    header = header & ";uretim_sekli"
    header = header & ";malzeme"
    header = header & ";malzeme_ebat"
    header = header & ";alt_kod"
    header = header & ";revizyon"
    header = header & ";tarih"
    
    ' --- AGAC TARAMA BASLAT ---
    TraverseComponent swRootComp, 1
    
    ' --- SUPPRESS UYARISI ---
    If suppressedDict.count > 0 Then
        Dim suppressedMsg As String
        Dim suppKey As Variant
        Dim suppCount As Long
        suppCount = 0
        
        suppressedMsg = suppressedDict.count & " adet suppress edilmis bilesen türü tespit edildi:" & vbCrLf & vbCrLf
        For Each suppKey In suppressedDict.Keys
            If suppressedDict(suppKey) > 1 Then
                suppressedMsg = suppressedMsg & "  " & Chr(149) & " " & suppKey & " (" & suppressedDict(suppKey) & " adet)" & vbCrLf
            Else
                suppressedMsg = suppressedMsg & "  " & Chr(149) & " " & suppKey & vbCrLf
            End If
            suppCount = suppCount + suppressedDict(suppKey)
        Next suppKey
        suppressedMsg = suppressedMsg & vbCrLf & "Toplam " & suppCount & " bilesen atlandi." & vbCrLf & _
                        "Devam etmek istiyor musunuz?"
        
        If MsgBox(suppressedMsg, vbYesNo + vbExclamation, "Uyari: Suppress Edilmis Bilesenler") = vbNo Then
            If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
            GoTo Cleanup
        End If
    End If
    
    ' --- BOS BOM KONTROLU ---
    If bomDict.count = 0 Then
        Dim failMsg As String
        failMsg = "Disa aktarilacak bilesen bulunamadi!" & vbCrLf & _
                  "Montaj dosyasinda bilesen olmayabilir veya tümü suppress edilmis olabilir."
        If errorLog <> "" Then failMsg = failMsg & vbCrLf & vbCrLf & "--- DETAYLAR ---" & vbCrLf & errorLog
        MsgBox failMsg, vbExclamation, "Uyari"
        If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
        GoTo Cleanup
    End If
    
    ' --- UTF-8 BOM'SUZ DOSYA YAZMA ---
    Dim utf8Stream As Object
    Set utf8Stream = CreateObject("ADODB.Stream")
    utf8Stream.Type = 2        ' adTypeText
    utf8Stream.Charset = "utf-8"
    utf8Stream.Open
    
    utf8Stream.WriteText header & vbCrLf
    
    Dim key As Variant
    Dim csvLine As String
    For Each key In bomDict.Keys
        csvLine = bomDict(key)
        csvLine = Replace(csvLine, "{{QTY_PH}}", CStr(CLng(qtyDict(key))))
        utf8Stream.WriteText csvLine & vbCrLf
    Next key
    
    utf8Stream.Position = 0
    utf8Stream.Type = 1  ' adTypeBinary
    
    If utf8Stream.Size > 3 Then utf8Stream.Position = 3
    
    Dim binStream As Object
    Set binStream = CreateObject("ADODB.Stream")
    binStream.Type = 1  ' adTypeBinary
    binStream.Open
    
    utf8Stream.CopyTo binStream
    binStream.SaveToFile filePath, 2  ' adSaveCreateOverWrite
    
    binStream.Close
    utf8Stream.Close
    Set binStream = Nothing
    Set utf8Stream = Nothing
    
    If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
    
    ' --- SONUC MESAJI ---
    Dim resultMsg As String
    Dim elapsed As Double
    elapsed = Timer - startTime
    If elapsed < 0 Then elapsed = elapsed + 86400
    
    resultMsg = "Masaüstüne basariyla aktarildi!" & vbCrLf & _
           "Toplam Satir: " & bomDict.count & vbCrLf & _
           "Islenen Bilesen: " & totalComponents & vbCrLf & _
           "Süre: " & Round(elapsed, 1) & " saniye" & vbCrLf & _
           "Dosya: " & filePath
    
    If errorLog <> "" Then resultMsg = resultMsg & vbCrLf & vbCrLf & "--- UYARILAR ---" & vbCrLf & errorLog
    MsgBox resultMsg, vbInformation, "Islem Tamam"
    GoTo Cleanup

ErrorHandler:
    On Error Resume Next
    If Not swModelView Is Nothing Then swModelView.EnableGraphicsUpdate = True
    If Not utf8Stream Is Nothing Then utf8Stream.Close
    If Not binStream Is Nothing Then binStream.Close
    MsgBox "Hata olustu: " & Err.Description & vbCrLf & "Kaynak: " & Err.Source, vbCritical, "Makro Hatasi"

Cleanup:
    On Error Resume Next
    Set bomDict = Nothing
    Set qtyDict = Nothing
    Set modelCache = Nothing
    Set suppressedDict = Nothing
    Set traversedSubAsm = Nothing
    Set swRootComp = Nothing
    Set swConf = Nothing
    Set swModel = Nothing
End Sub

' ============================================================================
' AGAC TARAMA FONKSIYONU (RECURSIVE)
' ============================================================================
Sub TraverseComponent(swComp As Object, nLevel As Long)
    Dim vChildComp As Variant
    Dim swChildComp As Object
    Dim parentName As String
    Dim childName As String
    Dim confName As String
    Dim uniqueKey As String
    Dim i As Long
    Dim isSuppressed As Boolean
    Dim childPath As String
    Dim traverseKey As String
    
    On Error Resume Next
    vChildComp = swComp.GetChildren
    On Error GoTo 0
    
    If IsEmpty(vChildComp) Then Exit Sub
    
    If nLevel = 1 Then
        parentName = GetFileNameWithoutExtension(swModel.GetTitle)
    Else
        parentName = GetComponentRef(swComp)
    End If
    
    For i = 0 To UBound(vChildComp)
        Set swChildComp = vChildComp(i)
        
        If swChildComp Is Nothing Then GoTo NextComponent
        
        On Error Resume Next
        isSuppressed = swChildComp.isSuppressed
        If Err.Number <> 0 Then
            Err.Clear
            GoTo NextComponent
        End If
        On Error GoTo 0
        
        If isSuppressed Then
            skippedComponents = skippedComponents + 1
            childName = GetComponentRef(swChildComp)
            If suppressedDict.Exists(childName) Then
                suppressedDict(childName) = suppressedDict(childName) + 1
            Else
                suppressedDict.Add childName, 1
            End If
            GoTo NextComponent
        End If
        
        totalComponents = totalComponents + 1
        If totalComponents Mod 200 = 0 Then DoEvents
        
        childName = GetComponentRef(swChildComp)
        
        On Error Resume Next
        confName = swChildComp.ReferencedConfiguration
        If Err.Number <> 0 Then
            confName = ""
            Err.Clear
        End If
        On Error GoTo 0
        
        uniqueKey = parentName & "|" & childName & "|" & confName
        
        If bomDict.Exists(uniqueKey) Then
            qtyDict(uniqueKey) = qtyDict(uniqueKey) + 1
        Else
            bomDict.Add uniqueKey, BuildComponentLine(swChildComp, parentName, childName, confName)
            qtyDict.Add uniqueKey, 1
        End If
        
        childPath = swChildComp.GetPathName
        traverseKey = childPath & "|" & confName
        
        If childPath <> "" Then
            If Not traversedSubAsm.Exists(traverseKey) Then
                traversedSubAsm.Add traverseKey, True
                TraverseComponent swChildComp, nLevel + 1
            End If
        Else
            TraverseComponent swChildComp, nLevel + 1
        End If
NextComponent:
    Next i
End Sub

' ============================================================================
' BILESEN SATIRI OLUSTURMA (9 sütun)
' ============================================================================
Function BuildComponentLine(swComp As Object, parentName As String, childName As String, confName As String) As String
    Dim swMod As Object
    Dim line As String
    
    Set swMod = GetCachedModel(swComp)
    
    ' Temel Bilgiler
    line = SafeCSV(parentName)
    line = line & ";" & SafeCSV(childName)
    line = line & ";{{QTY_PH}}"
    
    ' 6 Custom Property
    line = line & ";" & GetCP(swMod, confName, CP_URETIM_SEKLI)
    line = line & ";" & GetCP(swMod, confName, CP_MALZEME)
    line = line & ";" & GetCP(swMod, confName, CP_MALZEME_EBAT)
    line = line & ";" & GetCP(swMod, confName, CP_ALT_KOD)
    line = line & ";" & GetCP(swMod, confName, CP_REVIZYON)
    line = line & ";" & GetCP(swMod, confName, CP_TARIH)
    
    BuildComponentLine = line
End Function

' ============================================================================
' CUSTOM PROPERTY OKUMA
' ============================================================================
Function GetCP(swMod As Object, confName As String, propName As String) As String
    On Error Resume Next
    Dim val As String
    Dim resolvedVal As String
    
    GetCP = ""
    If swMod Is Nothing Then Exit Function
    
    swMod.Extension.CustomPropertyManager(confName).Get2 propName, val, resolvedVal
    
    If resolvedVal = "" Then
        swMod.Extension.CustomPropertyManager("").Get2 propName, val, resolvedVal
    End If
    
    GetCP = SafeCSV(resolvedVal)
End Function

' ============================================================================
' YARDIMCI FONKSIYONLAR
' ============================================================================
Function GetComponentRef(swComp As Object) As String
    On Error Resume Next
    Dim path As String
    Dim fileName As String
    
    path = swComp.GetPathName
    If path = "" Then
        fileName = swComp.Name2
        If InStr(fileName, "^") > 0 Then fileName = Left(fileName, InStr(fileName, "^") - 1)
    Else
        fileName = Mid(path, InStrRev(path, "\") + 1)
        If InStr(fileName, ".") > 0 Then fileName = Left(fileName, InStrRev(fileName, ".") - 1)
    End If
    GetComponentRef = fileName
End Function

Function GetFileNameWithoutExtension(ByVal fname As String) As String
    If InStr(fname, ".") > 0 Then
        GetFileNameWithoutExtension = Left(fname, InStrRev(fname, ".") - 1)
    Else
        GetFileNameWithoutExtension = fname
    End If
End Function

Function GetCachedModel(swComp As Object) As Object
    On Error Resume Next
    Dim path As String
    Dim swMod As Object
    
    path = swComp.GetPathName
    If path = "" Then
        Set GetCachedModel = swComp.GetModelDoc2
        Exit Function
    End If
    
    If modelCache.Exists(path) Then
        Set GetCachedModel = modelCache(path)
        Exit Function
    End If
    
    Set swMod = swComp.GetModelDoc2
    If Not swMod Is Nothing Then
        modelCache.Add path, swMod
    End If
    Set GetCachedModel = swMod
End Function

Function SafeCSV(ByVal val As String) As String
    If val = "" Then
        SafeCSV = ""
        Exit Function
    End If
    
    val = Replace(val, vbCrLf, " ")
    val = Replace(val, vbCr, " ")
    val = Replace(val, vbLf, " ")
    val = Trim(val)
    
    If val = "" Then
        SafeCSV = ""
        Exit Function
    End If
    
    Dim needsQuoting As Boolean
    needsQuoting = (InStr(val, ";") > 0)
    
    If InStr(val, """") > 0 Then
        val = Replace(val, """", """""")
        needsQuoting = True
    End If
    
    If needsQuoting Then
        SafeCSV = """" & val & """"
    Else
        SafeCSV = val
    End If
End Function
