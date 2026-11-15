// MOCK DATA ONLY. Shapes here mirror the backend contract in README.md.
export const seed={
 user:{id:'u1',name:'Student',email:'student@example.com',program:'BS Computer Science'},
 tasks:[
  {id:'t1',title:'Programming Activity 05',course:'Computer Programming',category:'Assignment',deadline:'2026-11-01',priority:'High',progress:65},
  {id:'t2',title:'Research Paper: Artificial Intelligence',course:'Research Methods',category:'Research',deadline:'2026-11-03',priority:'High',progress:20},
  {id:'t3',title:'Database Design Project',course:'Database Systems',category:'Project',deadline:'2026-11-06',priority:'Medium',progress:45},
  {id:'t4',title:'Operating Systems Quiz',course:'Operating Systems',category:'Examination',deadline:'2026-11-08',priority:'Medium',progress:0},
  {id:'t5',title:'UI/UX Reflection',course:'Human Computer Interaction',category:'Assignment',deadline:'2026-11-10',priority:'Low',progress:80}],
 settings:{name:'Student',program:'BS Computer Science',leadDays:2,sessionMinutes:45,weeklySummary:true},
 reminderPrefs:{deadline:true,dailySummary:true,progressCheckin:false,quietHours:true},
 history:{completed:12,completionRate:76,onTimeRate:84,weeklyChange:8,weeklyProductivity:[4,6,5,8,5,3,2],weeklyCompletion:[2,4,5,7],
  insight:'Your recorded activity shows research tasks have been delayed more often than assignments this month. Try splitting research work into shorter sessions and setting an earlier personal target date.'}
};
