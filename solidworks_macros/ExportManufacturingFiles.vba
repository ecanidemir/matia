' =========================================================================
' SOLIDWORKS DÜZ AÇILIM (DXF) VE STEP EXPORT MAKROSU
' =========================================================================
' Bu makro aktif montajdaki tüm parçaları tarar ve "uretim_sekli" özelliğine
' göre CNC Torna/Freze için STEP, Lazer Kesim için DXF (düz açılım) export eder.
'
' Özellikler:
'   - Daha önce oluşturulmuş dosyaları atlar (artımlı export)
'   - DXF için klasör hiyerarşisi: DXF_EXPORT \ Malzeme \ Kalınlık \ dosya.dxf
'   - STEP için klasör hiyerarşisi: STEP_EXPORT \ uretim_sekli \ dosya.step
'   - Hata ve eksik özellikleri export_raporu.txt'ye yazar
' =========================================================================

Dim swApp As SldWorks.SldWorks
Dim swModel As SldWorks.ModelDoc2
Dim swAsm As SldWorks.AssemblyDoc
Dim fso As Object

Dim baseDxfPath As String
Dim baseStepPath As String
Dim reportPath As String

Dim processedPats As Object ' Scripting.Dictionary
Dim reportLines As Collection ' VBA Collection

' Sayaçlar
Dim dxfCount As Long
Dim stepCount As Long
Dim skippedCount As Long
Dim missingCount As Long

Sub Main()
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    
    If swModel Is Nothing Then
        MsgBox "Lütfen bir montaj dosyası açın.", vbCritical
        Exit Sub
    End If
    
    If swModel.GetType <> swDocASSEMBLY Then
        MsgBox "Bu makro sadece montaj dosyalarında çalışır.", vbCritical
        Exit Sub
    End If

    ' Export klasörlerini ayarla
    Dim asmPath As String
    asmPath = swModel.GetPathName
    If asmPath = "" Then
        MsgBox "Lütfen önce montaj dosyasını kaydedin.", vbExclamation
        Exit Sub
    End If
    
    Set fso = CreateObject("Scripting.FileSystemObject")
    Dim asmDir As String
    asmDir = fso.GetParentFolderName(asmPath)
    
    baseDxfPath = asmDir & "\DXF_EXPORT"
    baseStepPath = asmDir & "\STEP_EXPORT"
    reportPath = asmDir & "\export_raporu.txt"
    
    If Not fso.FolderExists(baseDxfPath) Then fso.CreateFolder (baseDxfPath)
    If Not fso.FolderExists(baseStepPath) Then fso.CreateFolder (baseStepPath)

    ' Dictionary ve Collection hazırlığı
    If Not processedPats Is Nothing Then processedPats.RemoveAll
    Set processedPats = CreateObject("Scripting.Dictionary")
    Set reportLines = New Collection
    
    dxfCount = 0
    stepCount = 0
    skippedCount = 0
    missingCount = 0
    
    swApp.SendMsgToUser2 "Üretim dosyaları export işlemi başlıyor. Lütfen bekleyin...", swMbInformation, swMbOk
    
    ' Ana montajın kendisi (varsa kendi teknik resmi için, ama genellikle parça aranır, atlıyoruz veya bırakıyoruz)
    ' Ancak biz genelde sac levha / torna parçası arıyoruz, o yüzden doğrudan alt bileşenleri tarıyoruz.
    
    Dim swConf As SldWorks.Configuration
    Dim swRootComp As SldWorks.Component2
    Set swConf = swModel.GetActiveConfiguration
    Set swRootComp = swConf.GetRootComponent3(True)
    
    Dim vComps As Variant
    Dim i As Long
    Dim mainChildComp As SldWorks.Component2
    
    vComps = swRootComp.GetChildren
    If Not IsEmpty(vComps) Then
        For i = 0 To UBound(vComps)
            Set mainChildComp = vComps(i)
            TraverseComponentStructure mainChildComp
        Next i
    End If
    
    WriteReport
    
    ' Sonuç göstergesi
    Dim summary As String
    summary = "İşlem tamamlandı!" & vbCrLf & vbCrLf & _
              "- Oluşturulan DXF: " & dxfCount & vbCrLf & _
              "- Oluşturulan STEP: " & stepCount & vbCrLf & _
              "- Zaten mevcut (Atlandı): " & skippedCount & vbCrLf & _
              "- Hatalı/Eksik (Atlandı): " & missingCount
              
    If missingCount > 0 Then
        summary = summary & vbCrLf & vbCrLf & "Detaylı Hata Raporu: " & reportPath
    End If
    
    swApp.SendMsgToUser2 summary, swMbInformation, swMbOk
    
    ' Temizlik
    Set processedPats = Nothing
    Set reportLines = Nothing
    Set fso = Nothing
End Sub

Sub TraverseComponentStructure(ByVal swComp As SldWorks.Component2)
    Dim vComps As Variant
    Dim childComp As SldWorks.Component2
    Dim i As Long
    
    If swComp.GetSuppression <> swComponentSuppressed Then
        Dim compModel As SldWorks.ModelDoc2
        Dim wasOpenedManually As Boolean
        wasOpenedManually = False
        Set compModel = swComp.GetModelDoc2
        
        ' Hafifletilmiş mod veya büyük montaj modunda çözümlenmemişse
        If compModel Is Nothing And (swComp.GetSuppression = 2 Or swComp.GetSuppression = 4) Then
            swComp.SetSuppression2 1 ' Çözümlenmişe çek
            Set compModel = swComp.GetModelDoc2
        End If
        
        ' Hala Nothing ise arkada sessizce aç
        If compModel Is Nothing Then
            Dim compPath As String
            compPath = swComp.GetPathName
            If compPath <> "" And fso.FileExists(compPath) Then
                Dim errVal As Long
                Dim warnVal As Long
                Dim docType As Long
                
                If UCase(Right(compPath, 6)) = "SLDASM" Then
                    docType = swDocASSEMBLY
                Else
                    docType = swDocPART
                End If
                
                Set compModel = swApp.OpenDoc6(compPath, docType, swOpenDocOptions_Silent Or swOpenDocOptions_ReadOnly, "", errVal, warnVal)
                If Not compModel Is Nothing Then wasOpenedManually = True
            End If
        End If
        
        ' Dosya bulundu ve model okunduysa işlem yap
        If Not compModel Is Nothing Then
            ' Alt montajların kendisinde genelde uretim_sekli Lazer olmaz ama yine de taratabiliriz
            If compModel.GetType = swDocPART Then
                ProcessPart compModel, swComp
            End If
            
            If wasOpenedManually Then
                swApp.CloseDoc compModel.GetTitle
            End If
        Else
            If swComp.GetPathName <> "" And UCase(Right(swComp.GetPathName, 6)) = "SLDPRT" Then
                reportLines.Add "[UYARI] """ & swComp.Name2 & """ fiziksel dsosuna erişilemedi."
            End If
        End If
        
        ' Çocukları gezin (Recursion)
        vComps = swComp.GetChildren
        If Not IsEmpty(vComps) Then
            For i = 0 To UBound(vComps)
                Set childComp = vComps(i)
                TraverseComponentStructure childComp
            Next i
        End If
    End If
End Sub

Sub ProcessPart(model As SldWorks.ModelDoc2, comp As SldWorks.Component2)
    Dim modelPath As String
    modelPath = model.GetPathName
    
    ' Konfigürasyon bazlı kontrol (Çalışan makrodan iyileştirme)
    Dim confName As String
    confName = comp.ReferencedConfiguration
    
    Dim uniqueKey As String
    uniqueKey = modelPath & "::" & confName
    
    If processedPats.Exists(uniqueKey) Then Exit Sub
    processedPats.Add uniqueKey, True
    
    Dim partName As String
    partName = fso.GetBaseName(modelPath)
    
    ' Eğer Default (Varsayılan) konfigürasyon değilse distinguishes için dosya adına eklenebilir ama 
    ' çoğu lazer/torna üretiminde 1 dosya 1 parça olduğu için dosya ismini şimdilik aynı tutuyoruz.
    
    ' Uretim sekli kontrolu
    Dim uretimSekli As String
    uretimSekli = Trim(GetCustomProperty(model, "uretim_sekli"))
    
    If uretimSekli = "" Then
        ' Uretim sekli bos olanlar atlanir
        Exit Sub
    End If
    
    ' Montajda kullanılan spesifik konfigürasyonu aktif etme (Çalışan STEP makrosundan en önemli geliştirme)
    Dim activeConf As String
    activeConf = model.ConfigurationManager.ActiveConfiguration.Name
    If activeConf <> confName Then
        model.ShowConfiguration2 confName
    End If
    
    ' ==========================================
    ' DURUM 1: LAZER KESIM (DXF FLAT PATTERN)
    ' ==========================================
    If LCase(uretimSekli) = "laser cut (lazer)" Or LCase(uretimSekli) = "laser cut (lazer)" Then ' Tam kelime kontrolü
        
        Dim malzeme As String
        malzeme = Trim(GetCustomProperty(model, "malzeme"))
        Dim kalinlik As String
        kalinlik = Trim(GetSheetMetalThickness(model))
        
        ' Eksik özellik kontrolü
        If malzeme = "" Or kalinlik = "" Or kalinlik = "0" Then
            missingCount = missingCount + 1
            reportLines.Add "[EKSİK] """ & partName & """ DXF atlandı. (Malzeme veya Kalınlık bilgisi hatalı/yok)"
            Exit Sub
        End If
        
        ' Klasor Hiyerarsisi: DXF_EXPORT \ Malzeme \ Kalınlık
        malzeme = CleanFileName(malzeme)
        kalinlik = CleanFileName(kalinlik) & " mm" ' mm ekleyelim klasör anlaşılır olsun
        
        Dim targetFolder As String
        targetFolder = baseDxfPath & "\" & malzeme
        If Not fso.FolderExists(targetFolder) Then fso.CreateFolder (targetFolder)
        
        targetFolder = targetFolder & "\" & kalinlik
        If Not fso.FolderExists(targetFolder) Then fso.CreateFolder (targetFolder)
        
        Dim dxfPath As String
        dxfPath = targetFolder & "\" & partName & ".dxf"
        
        If fso.FileExists(dxfPath) Then
            skippedCount = skippedCount + 1
            reportLines.Add "[ATLANDI] """ & partName & ".dxf"" zaten mevcut."
            Exit Sub
        End If
        
        ' Modeli açıp DXF export
        If ExportFlatPatternDXF(model, dxfPath) Then
            dxfCount = dxfCount + 1
        Else
            missingCount = missingCount + 1
            reportLines.Add "[HATA] """ & partName & """ DXF export başarısız. (Parça sac levha olmayabilir veya flat pattern (düz açılım) pasif olabilir)"
            If fso.FileExists(dxfPath) Then fso.DeleteFile dxfPath
        End If

    ' ==========================================
    ' DURUM 2: TORNA / FREZE (STEP EXPORT)
    ' ==========================================
    ElseIf LCase(uretimSekli) = "lathe (torna)" Or LCase(uretimSekli) = "milling (freze)" Then
        
        Dim stepFolder As String
        stepFolder = baseStepPath & "\" & CleanFileName(uretimSekli)
        If Not fso.FolderExists(stepFolder) Then fso.CreateFolder (stepFolder)
        
        Dim stepPath As String
        stepPath = stepFolder & "\" & partName & ".step"
        
        If fso.FileExists(stepPath) Then
            skippedCount = skippedCount + 1
            reportLines.Add "[ATLANDI] """ & partName & ".step"" zaten mevcut."
            Exit Sub
        End If
        
        Dim errObj As Long
        Dim warnObj As Long
        Dim saveStatus As Boolean
        
        ' 0=swSaveAsCurrentVersion, 1=swSaveAsOptions_Silent
        saveStatus = model.Extension.SaveAs(stepPath, 0, 1, Nothing, errObj, warnObj)
        
        If saveStatus And fso.FileExists(stepPath) Then
            stepCount = stepCount + 1
        Else
            missingCount = missingCount + 1
            reportLines.Add "[HATA] """ & partName & """ STEP export başarısız."
        End If
    End If
End Sub

' -------------------------------------------------------------
' DXF (Flat Pattern) Export Fonksiyonu
' -------------------------------------------------------------
Function ExportFlatPatternDXF(model As SldWorks.ModelDoc2, dxfPath As String) As Boolean
    Dim bRet As Boolean
    bRet = False
    
    On Error GoTo ErrorHandler
    
    Dim currentActiveDoc As SldWorks.ModelDoc2
    Set currentActiveDoc = swApp.ActiveDoc
    
    Dim errs As Long
    ' Parçayı aktifleştir (Çalışan makrodan iyileştirme: GetPathName ve rebuild yapmadan)
    swApp.ActivateDoc3 model.GetPathName, False, 2, errs ' 2 = swDontRebuildActiveDoc
    
    ' Performans için UI güncellemelerini durdur (Çalışan makrodan iyileştirme)
    model.FeatureManager.EnableFeatureTree = False
    model.FeatureManager.EnableFeatureTreeWindow = False
    model.ActiveView.EnableGraphicsUpdate = False
    
    Dim swPart As SldWorks.PartDoc
    Set swPart = model
    
    Dim options As Long
    options = 1  ' SW_EXPORT_GEOMETRY (SheetMetalOptions_e.ExportFlatPatternGeometry = 1)
    
    ' FlatPattern unsurunu bul (Çalışan makrodan iyileştirme)
    Dim flatPatternFeat As SldWorks.Feature
    Set flatPatternFeat = FindFlatPatternFeature(model.FirstFeature)
    
    If Not flatPatternFeat Is Nothing Then
        ' Unsuru seçip export işlemini yapmak hizalama ve yanlış yüz seçimi kaynaklı hataları önler
        If flatPatternFeat.Select2(False, -1) Then
            ' 1 = swExportToDWG_ExportSheetMetal, varAlignment için Empty göndererek kendi doğal yönelimini korumasını sağlıyoruz
            bRet = swPart.ExportToDWG2(dxfPath, model.GetPathName, 1, True, Empty, False, False, options, Empty)
        Else
            bRet = swPart.ExportToDWG2(dxfPath, model.GetPathName, 1, True, Empty, False, False, options, Empty)
        End If
    Else
        ' FlatPattern unsuru bulunamazsa doğrudan ExportToDWG2 deniyoruz (Fallback)
        bRet = swPart.ExportToDWG2(dxfPath, model.GetPathName, 1, True, Empty, False, False, options, Empty)
    End If
    
    ' Eğer başarısız olursa eski ama sağlam olan ExportFlatPatternView metodunu dene
    If Not bRet Then
        bRet = swPart.ExportFlatPatternView(dxfPath, options)
    End If
    
Cleanup:
    On Error Resume Next
    ' UI güncellemelerini geri aç
    model.FeatureManager.EnableFeatureTree = True
    model.FeatureManager.EnableFeatureTreeWindow = True
    model.ActiveView.EnableGraphicsUpdate = True
    
    ' Tekrar eski aktif dökümana (montaja) dön
    If Not currentActiveDoc Is Nothing Then
        swApp.ActivateDoc3 currentActiveDoc.GetPathName, False, 2, errs
    End If
    
    ExportFlatPatternDXF = bRet
    Exit Function

ErrorHandler:
    bRet = False
    GoTo Cleanup
End Function

' -------------------------------------------------------------
' Unsur Ağacında FlatPattern (Düz Açılım) Arama (Rekürsif)
' -------------------------------------------------------------
Function FindFlatPatternFeature(swFeat As SldWorks.Feature) As SldWorks.Feature
    If swFeat Is Nothing Then Exit Function
    
    Do While Not swFeat Is Nothing
        If swFeat.GetTypeName2() = "FlatPattern" Then
            Set FindFlatPatternFeature = swFeat
            Exit Function
        End If
        
        Dim swSubFeat As SldWorks.Feature
        Set swSubFeat = swFeat.GetFirstSubFeature
        If Not swSubFeat Is Nothing Then
            Dim foundFeat As SldWorks.Feature
            Set foundFeat = FindFlatPatternFeature(swSubFeat)
            If Not foundFeat Is Nothing Then
                Set FindFlatPatternFeature = foundFeat
                Exit Function
            End If
        End If
        
        Set swFeat = swFeat.GetNextFeature
    Loop
    Set FindFlatPatternFeature = Nothing
End Function

' -------------------------------------------------------------
' Custom Property Okuma
' -------------------------------------------------------------
Function GetCustomProperty(model As SldWorks.ModelDoc2, propName As String) As String
    On Error Resume Next
    Dim val As String
    Dim resVal As String
    Dim swCustProp As SldWorks.CustomPropertyManager
    
    Set swCustProp = model.Extension.CustomPropertyManager(model.ConfigurationManager.ActiveConfiguration.Name)
    swCustProp.Get4 propName, False, val, resVal
    
    If resVal = "" Then
        Set swCustProp = model.Extension.CustomPropertyManager("")
        swCustProp.Get4 propName, False, val, resVal
    End If
    
    GetCustomProperty = Trim(resVal)
End Function

' -------------------------------------------------------------
' Sac Kalınlığı (Thickness) Okuma
' -------------------------------------------------------------
Function GetSheetMetalThickness(model As SldWorks.ModelDoc2) As String
    On Error Resume Next
    Dim thk As String
    
    ' 1. Önce özelliklerden "Thickness" veya "Kalınlık" çekmeyi dener
    thk = GetCustomProperty(model, "Thickness")
    If thk = "" Then thk = GetCustomProperty(model, "Kalınlık")
    
    If thk <> "" Then
        GetSheetMetalThickness = CleanThicknessString(thk)
        Exit Function
    End If
    
    ' 2. Özel özellik yoksa FeatureManager (Unsur Ağacı) üzerinden Sac Levha Unsurunu bulur
    Dim feat As SldWorks.Feature
    Set feat = model.FirstFeature
    Do While Not feat Is Nothing
        If feat.GetTypeName2 = "SheetMetal" Or feat.GetTypeName2 = "SMBaseFlange" Then
            Dim smFeatData As Object
            Set smFeatData = feat.GetDefinition
            If Not smFeatData Is Nothing Then
                Dim numThk As Double
                numThk = smFeatData.Thickness * 1000# ' Metreyi milimetreye çevirir
                GetSheetMetalThickness = Replace(CStr(numThk), ",", ".")
                Exit Function
            End If
        End If
        Set feat = feat.GetNextFeature
    Loop
    
    GetSheetMetalThickness = "0"
End Function

Function CleanThicknessString(val As String) As String
    Dim t As String
    t = LCase(val)
    t = Replace(t, " mm", "")
    t = Replace(t, "mm", "")
    t = Replace(t, """", "")
    t = Replace(t, ",", ".")
    CleanThicknessString = Trim(t)
End Function

' -------------------------------------------------------------
' Klasör ve Dosya İsmi Temizleme
' -------------------------------------------------------------
Function CleanFileName(fileName As String) As String
    Dim invalidChars As String
    invalidChars = "/\:*?""<>|." ' Noktayı özel dahil ediyoruz (. kullanıcalr kalınlıkta verebilir ama klasor adi için riskli mi? Hayir, klasörde . olabilir, ama en sonda . olursa hata verebilir. Şimdilik nokta kalsın ama / vs engellensin)
    ' Windows klasör/dosya isimlerinde tehlikeli karakterler
    Dim i As Integer
    Dim result As String
    result = fileName
    For i = 1 To Len(invalidChars)
        result = Replace(result, Mid(invalidChars, i, 1), "_")
    Next i
    CleanFileName = result
End Function

' -------------------------------------------------------------
' Rapor Yazdırma
' -------------------------------------------------------------
Sub WriteReport()
    If reportLines Is Nothing Then Exit Sub
    If reportLines.Count = 0 Then Exit Sub
    
    Dim ts As Object
    Set ts = fso.OpenTextFile(reportPath, 8, True) ' 8 = ForAppending, True = Create if not exists
    
    ts.WriteLine ""
    ts.WriteLine "========================================================"
    ts.WriteLine "ÜRETİM EXPORT RAPORU - " & Format(Now, "yyyy-MM-dd HH:mm:ss")
    ts.WriteLine "========================================================"
    ts.WriteLine "Oluşturulan DXF : " & dxfCount
    ts.WriteLine "Oluşturulan STEP: " & stepCount
    ts.WriteLine "Atlanan (Mevcut) : " & skippedCount
    ts.WriteLine "Hatalı/Eksik (Atlanan): " & missingCount
    ts.WriteLine "========================================================"
    ts.WriteLine ""
    
    Dim j As Long
    For j = 1 To reportLines.Count
        ts.WriteLine reportLines(j)
    Next j
    
    ts.WriteLine ""
    ts.Close
End Sub
